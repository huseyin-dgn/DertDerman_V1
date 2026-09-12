from dataclasses import dataclass
from hashlib import sha256

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email


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
        return ResendProvider(api_key=getattr(settings, "RESEND_API_KEY", ""))
    except ResendConfigurationError as exc:
        raise EmailConfigurationError("Resend is not configured.") from exc


def send_email(
    *,
    recipient_email: str,
    subject: str,
    html_body: str,
    text_body: str,
    event_key: str,
    from_email: str | None = None,
    reply_to: str | None = None,
) -> EmailSendResult:
    """
    Provider-neutral email boundary.

    Business rules, token generation and notification policy stay outside this
    function. This layer only validates a complete message and sends it through
    the configured provider.
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

    if not getattr(settings, "EMAIL_SENDING_ENABLED", False):
        return EmailSendResult(
            provider=provider_name,
            status="skipped",
            idempotency_key=idempotency_key,
        )

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

    return EmailSendResult(
        provider=provider_name,
        status="sent",
        provider_message_id=provider_message_id,
        idempotency_key=idempotency_key,
    )
