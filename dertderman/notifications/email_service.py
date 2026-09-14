import logging
from dataclasses import dataclass
from hashlib import sha256

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import F
from django.utils import timezone


logger = logging.getLogger(__name__)


class EmailServiceError(RuntimeError):
    """Base error for the application email boundary."""


class EmailConfigurationError(EmailServiceError):
    """Raised when email configuration or message input is invalid."""


class EmailDeliveryError(EmailServiceError):
    """Raised when the configured provider cannot deliver a message."""


@dataclass(frozen=True)
class EmailSendResult:
    provider: str
    status: str
    provider_message_id: str | None = None
    idempotency_key: str | None = None


def build_provider_idempotency_key(*, event_key: str, recipient_email: str) -> str:
    event_key = (event_key or "").strip()
    recipient_email = (recipient_email or "").strip().casefold()

    if not event_key:
        raise EmailConfigurationError("Email event_key is required.")

    if not recipient_email:
        raise EmailConfigurationError("Recipient email is required.")

    digest = sha256(f"{event_key}\0{recipient_email}".encode("utf-8")).hexdigest()
    return f"dertderman/{digest}"


def build_recipient_hash(recipient_email: str) -> str:
    normalized = (recipient_email or "").strip().casefold()
    if not normalized:
        raise EmailConfigurationError("Recipient email is required.")
    return sha256(normalized.encode("utf-8")).hexdigest()


def _validate_recipient(email: str) -> str:
    email = (email or "").strip()

    try:
        validate_email(email)
    except ValidationError as exc:
        raise EmailConfigurationError("Recipient email is invalid.") from exc

    return email


def _required(value: str, label: str) -> str:
    value = (value or "").strip()
    if not value:
        raise EmailConfigurationError(f"{label} is required.")
    return value


def _resend_provider():
    from .email_providers.resend import ResendConfigurationError, ResendProvider

    try:
        return ResendProvider(
            api_key=getattr(settings, "RESEND_API_KEY", ""),
            timeout_seconds=getattr(settings, "RESEND_TIMEOUT_SECONDS", 30),
        )
    except ResendConfigurationError as exc:
        raise EmailConfigurationError("Resend is not configured.") from exc


def _load_or_create_delivery(
    *,
    provider_name: str,
    idempotency_key: str,
    recipient_email: str,
    notification=None,
):
    from .models import EmailDelivery

    delivery, created = EmailDelivery.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "notification": notification,
            "provider": provider_name,
            "recipient_hash": build_recipient_hash(recipient_email),
            "status": EmailDelivery.Status.PENDING,
        },
    )

    if (
        not created
        and notification is not None
        and delivery.notification_id is None
    ):
        EmailDelivery.objects.filter(
            pk=delivery.pk,
            notification__isnull=True,
        ).update(
            notification=notification,
            updated_at=timezone.now(),
        )
        delivery.notification = notification

    return delivery, created


def _terminal_result(delivery) -> EmailSendResult | None:
    from .models import EmailDelivery

    if delivery.status == EmailDelivery.Status.SENT:
        return EmailSendResult(
            provider=delivery.provider,
            status="sent",
            provider_message_id=delivery.provider_message_id or None,
            idempotency_key=delivery.idempotency_key,
        )

    # SKIPPED kalıcı terminal durum değildir. Gönderim o anda kapalıysa
    # yeniden SKIPPED döner; daha sonra gönderim açılırsa aynı event tekrar
    # transport katmanına alınabilir.
    return None


def _mark_skipped(delivery, provider_name: str) -> None:
    from .models import EmailDelivery

    delivery.provider = provider_name
    delivery.status = EmailDelivery.Status.SKIPPED
    delivery.last_error_type = ""
    delivery.sent_at = None
    delivery.save(
        update_fields=[
            "provider",
            "status",
            "last_error_type",
            "sent_at",
            "updated_at",
        ]
    )


def _claim_attempt(delivery, *, created: bool, provider_name: str) -> None:
    from .models import EmailDelivery

    if created:
        delivery.provider = provider_name
        delivery.status = EmailDelivery.Status.PENDING
        delivery.attempt_count = 1
        delivery.last_error_type = ""
        delivery.save(
            update_fields=[
                "provider",
                "status",
                "attempt_count",
                "last_error_type",
                "updated_at",
            ]
        )
        return

    if delivery.status == EmailDelivery.Status.PENDING:
        raise EmailDeliveryError("Email delivery is already being processed.")

    retryable_statuses = (
        EmailDelivery.Status.FAILED,
        EmailDelivery.Status.SKIPPED,
    )
    if delivery.status not in retryable_statuses:
        raise EmailDeliveryError("Email delivery cannot be attempted again.")

    updated = EmailDelivery.objects.filter(
        pk=delivery.pk,
        status__in=retryable_statuses,
    ).update(
        provider=provider_name,
        status=EmailDelivery.Status.PENDING,
        attempt_count=F("attempt_count") + 1,
        last_error_type="",
        updated_at=timezone.now(),
    )

    if updated != 1:
        raise EmailDeliveryError("Email delivery is already being processed.")

    delivery.refresh_from_db()


def _mark_failed(delivery, error_type: str) -> None:
    from .models import EmailDelivery

    delivery.status = EmailDelivery.Status.FAILED
    delivery.last_error_type = (error_type or "")[:128]
    delivery.sent_at = None
    delivery.save(
        update_fields=[
            "status",
            "last_error_type",
            "sent_at",
            "updated_at",
        ]
    )


def _mark_sent(delivery, provider_message_id: str) -> None:
    from .models import EmailDelivery

    delivery.status = EmailDelivery.Status.SENT
    delivery.provider_message_id = (provider_message_id or "")[:255]
    delivery.last_error_type = ""
    delivery.sent_at = timezone.now()
    delivery.save(
        update_fields=[
            "status",
            "provider_message_id",
            "last_error_type",
            "sent_at",
            "updated_at",
        ]
    )

    try:
        from .webhook_service import reconcile_unmatched_resend_events
        reconcile_unmatched_resend_events(delivery.provider_message_id)
    except Exception as exc:
        logger.warning(
            "Email webhook reconciliation failed: delivery_id=%s exception_type=%s",
            delivery.pk,
            exc.__class__.__name__,
        )


def send_email(
    *,
    recipient_email: str,
    subject: str,
    html_body: str,
    text_body: str,
    event_key: str,
    from_email: str | None = None,
    reply_to: str | None = None,
    notification=None,
) -> EmailSendResult:
    """
    Provider-neutral email boundary with persistent delivery idempotency.

    Raw recipient addresses, message bodies, token-bearing URLs and provider
    error payloads are never persisted in EmailDelivery.
    """

    recipient_email = _validate_recipient(recipient_email)
    subject = _required(subject, "Email subject")
    html_body = _required(html_body, "Email HTML body")
    text_body = _required(text_body, "Email text body")
    event_key = _required(event_key, "Email event_key")

    provider_name = (
        getattr(settings, "EMAIL_PROVIDER", "resend") or "resend"
    ).strip().lower()

    idempotency_key = build_provider_idempotency_key(
        event_key=event_key,
        recipient_email=recipient_email,
    )

    delivery, created = _load_or_create_delivery(
        provider_name=provider_name,
        idempotency_key=idempotency_key,
        recipient_email=recipient_email,
        notification=notification,
    )

    terminal = _terminal_result(delivery)
    if terminal is not None:
        return terminal

    if not created:
        from .models import EmailDelivery

        if delivery.status == EmailDelivery.Status.PENDING:
            raise EmailDeliveryError("Email delivery is already being processed.")

    if not getattr(settings, "EMAIL_SENDING_ENABLED", False):
        _mark_skipped(delivery, provider_name)
        return EmailSendResult(
            provider=provider_name,
            status="skipped",
            idempotency_key=idempotency_key,
        )

    _claim_attempt(
        delivery,
        created=created,
        provider_name=provider_name,
    )

    try:
        if provider_name != "resend":
            raise EmailConfigurationError("Unsupported email provider.")

        from_email = _required(
            from_email or getattr(settings, "DEFAULT_FROM_EMAIL", ""),
            "From email",
        )
        reply_to = _required(
            reply_to or getattr(settings, "EMAIL_REPLY_TO", ""),
            "Reply-To email",
        )

        provider = _resend_provider()

        from .email_providers.resend import (
            ResendConfigurationError,
            ResendDeliveryError,
        )

        try:
            provider_message_id = provider.send(
                recipient_email=recipient_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                from_email=from_email,
                reply_to=reply_to,
                idempotency_key=idempotency_key,
            )
        except ResendConfigurationError as exc:
            raise EmailConfigurationError("Resend is not configured.") from exc
        except ResendDeliveryError as exc:
            raise EmailDeliveryError("Email provider delivery failed.") from exc

    except EmailServiceError as exc:
        _mark_failed(delivery, exc.__class__.__name__)
        raise

    _mark_sent(delivery, provider_message_id)

    return EmailSendResult(
        provider=provider_name,
        status="sent",
        provider_message_id=provider_message_id,
        idempotency_key=idempotency_key,
    )
