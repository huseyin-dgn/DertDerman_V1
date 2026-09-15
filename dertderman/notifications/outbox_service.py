import hashlib
import json
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parseaddr

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail.message import sanitize_address
from django.core.validators import validate_email
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.template import TemplateDoesNotExist, TemplateSyntaxError
from django.template.loader import get_template
from django.utils import timezone

from config.validation import validate_site_base_url

from .email_providers.resend import (
    ResendConfigurationError,
    ResendDeliveryError,
    ResendProvider,
    _load_resend,
)
from .email_service import (
    EmailSendResult,
    _required,
    _validate_recipient,
    build_recipient_hash,
)
from .email_template_manifest import required_email_template_names
from .models import EmailDelivery, EmailOutbox
from .provider_identifiers import (
    validate_provider_message_id,
)


logger = logging.getLogger(__name__)

DEFAULT_LEASE_SECONDS = 120
PROVIDER_RETRY_WINDOW = timedelta(hours=23)
MAX_BACKOFF_SECONDS = 60 * 60
MAX_RENDER_FAILURES = 5
RENDER_RETRY_BASE_SECONDS = 30
RENDER_RETRY_MAX_SECONDS = 240
PASSWORD_RESET_NOOP_RETENTION = timedelta(hours=24)
PASSWORD_RESET_NOOP_CLEANUP_BATCH_SIZE = 100


class OutboxError(RuntimeError):
    """Base error for durable email processing."""


class OutboxClaimLost(OutboxError):
    """The caller no longer owns the outbox lease."""


class OutboxConfigurationError(OutboxError):
    """Global worker configuration is invalid; queued items stay intact."""


OUTBOX_UNSUPPORTED_TEMPLATE_VERSION = "OUTBOX_UNSUPPORTED_TEMPLATE_VERSION"
OUTBOX_INVALID_RECIPE = "OUTBOX_INVALID_RECIPE"
OUTBOX_PROVIDER_MISMATCH = "OUTBOX_PROVIDER_MISMATCH"
OUTBOX_PROVIDER_MESSAGE_OWNERSHIP_CONFLICT = (
    "OUTBOX_PROVIDER_MESSAGE_OWNERSHIP_CONFLICT"
)
OUTBOX_RENDER_RETRY_EXHAUSTED = "OUTBOX_RENDER_RETRY_EXHAUSTED"
_PERMANENT_ITEM_ERROR_CODES = frozenset(
    {
        OUTBOX_UNSUPPORTED_TEMPLATE_VERSION,
        OUTBOX_INVALID_RECIPE,
        OUTBOX_PROVIDER_MISMATCH,
        OUTBOX_PROVIDER_MESSAGE_OWNERSHIP_CONFLICT,
    }
)


class OutboxPermanentItemError(OutboxError):
    """One persisted outbox recipe is permanently invalid."""

    def __init__(self, code):
        safe_code = str(code or "").strip().upper()
        if safe_code not in _PERMANENT_ITEM_ERROR_CODES:
            safe_code = OUTBOX_INVALID_RECIPE
        super().__init__("Email outbox item is permanently invalid.")
        self.code = safe_code[:64]


class OutboxRendererUnavailable(OutboxConfigurationError):
    """A producer-specific renderer has not been installed yet."""


class OutboxBusinessCancellation(OutboxError):
    """A claimed intent is no longer eligible for provider dispatch."""

    def __init__(self, code):
        super().__init__("Email outbox business cancellation.")
        self.code = (code or "OUTBOX_CANCELLED")[:64]


@dataclass(frozen=True)
class OutboxClaim:
    outbox_id: uuid.UUID
    claim_token: uuid.UUID


@dataclass(frozen=True)
class EmailPayload:
    recipient_email: str
    subject: str
    html_body: str
    text_body: str
    from_email: str
    reply_to: str


@dataclass(frozen=True)
class DispatchPreparation:
    previous_attempt_count: int
    previous_first_attempt_at: datetime | None
    previous_provider_retry_deadline_at: datetime | None
    prepared_attempt_count: int


def canonical_payload_hash(payload: EmailPayload) -> str:
    values = [
        payload.recipient_email.strip(),
        payload.from_email.strip(),
        payload.reply_to.strip(),
        payload.subject.strip(),
        payload.html_body,
        payload.text_body,
    ]
    serialized = json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _validate_outbox_provider(provider_name) -> None:
    configured_provider = (
        getattr(settings, "EMAIL_PROVIDER", "resend") or ""
    ).strip().lower()
    if provider_name != configured_provider:
        raise OutboxPermanentItemError(OUTBOX_PROVIDER_MISMATCH)


def validate_dispatch_configuration() -> None:
    if not getattr(settings, "EMAIL_SENDING_ENABLED", False):
        raise OutboxConfigurationError("Email sending is disabled.")

    configured_provider = (
        getattr(settings, "EMAIL_PROVIDER", "resend") or ""
    ).strip().lower()
    if configured_provider != "resend":
        raise OutboxConfigurationError("Unsupported email provider.")

    api_key = (getattr(settings, "RESEND_API_KEY", "") or "").strip()
    if not api_key:
        raise OutboxConfigurationError("Resend is not configured.")

    try:
        ResendProvider(
            api_key=api_key,
            timeout_seconds=getattr(settings, "RESEND_TIMEOUT_SECONDS", 30),
        )
    except ResendConfigurationError:
        raise OutboxConfigurationError("Resend is not configured.") from None

    try:
        _load_resend()
    except ResendConfigurationError:
        raise OutboxConfigurationError("Resend is not available.") from None


def _validate_mailbox_setting(setting_name) -> None:
    value = getattr(settings, setting_name, "")
    if not isinstance(value, str) or not value.strip():
        raise OutboxConfigurationError(
            f"{setting_name} must contain one valid mailbox."
        )
    try:
        sanitized = sanitize_address(value, "utf-8")
        _display_name, addr_spec = parseaddr(sanitized)
        validate_email(addr_spec)
    except (TypeError, ValueError, ValidationError):
        raise OutboxConfigurationError(
            f"{setting_name} must contain one valid mailbox."
        ) from None


def validate_required_email_templates() -> None:
    try:
        for template_name in required_email_template_names():
            get_template(template_name)
    except Exception:
        raise OutboxConfigurationError(
            "Required email templates are unavailable."
        ) from None


def validate_worker_configuration() -> None:
    validate_dispatch_configuration()
    _validate_mailbox_setting("DEFAULT_FROM_EMAIL")
    _validate_mailbox_setting("EMAIL_REPLY_TO")
    try:
        validate_site_base_url(
            getattr(settings, "SITE_BASE_URL", ""),
            require_https=getattr(settings, "IS_PRODUCTION", False),
        )
    except ValueError:
        raise OutboxConfigurationError("SITE_BASE_URL is invalid.") from None
    validate_required_email_templates()


def _claimable(now):
    return Q(
        status__in=(EmailOutbox.Status.PENDING, EmailOutbox.Status.RETRY),
        available_at__lte=now,
    ) | Q(
        status=EmailOutbox.Status.PROCESSING,
        lease_expires_at__lt=now,
    )


def claim_email_outbox(
    *,
    batch_size=25,
    lease_seconds=DEFAULT_LEASE_SECONDS,
    now=None,
):
    if batch_size < 1:
        raise ValueError("batch_size must be positive.")
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be positive.")

    now = now or timezone.now()
    lease_expires_at = now + timedelta(seconds=lease_seconds)
    claims = []

    with transaction.atomic():
        candidates = EmailOutbox.objects.filter(_claimable(now)).order_by(
            "available_at", "created_at", "pk"
        )
        if connection.features.has_select_for_update_skip_locked:
            candidates = candidates.select_for_update(skip_locked=True)

        candidate_ids = list(candidates.values_list("pk", flat=True)[:batch_size])
        for outbox_id in candidate_ids:
            claim_token = uuid.uuid4()
            updated = EmailOutbox.objects.filter(
                pk=outbox_id,
            ).filter(_claimable(now)).update(
                status=EmailOutbox.Status.PROCESSING,
                claim_token=claim_token,
                claimed_at=now,
                lease_expires_at=lease_expires_at,
                completed_at=None,
                updated_at=now,
            )
            if updated == 1:
                claims.append(OutboxClaim(outbox_id, claim_token))

    return claims


def _clear_claim(outbox):
    outbox.claim_token = None
    outbox.claimed_at = None
    outbox.lease_expires_at = None


def _owns_claim(outbox, claim_token, now):
    return (
        outbox.status == EmailOutbox.Status.PROCESSING
        and outbox.claim_token == claim_token
        and outbox.lease_expires_at is not None
        and outbox.lease_expires_at > now
    )


def _set_terminal(outbox, *, status, code, now, extra_update_fields=()):
    outbox.status = status
    outbox.last_error_code = code[:64]
    outbox.last_error_at = now if code else None
    outbox.completed_at = now
    _clear_claim(outbox)
    outbox.save(
        update_fields=[
            "status",
            "last_error_code",
            "last_error_at",
            "completed_at",
            "claim_token",
            "claimed_at",
            "lease_expires_at",
            "updated_at",
            *extra_update_fields,
        ]
    )


def _load_owned_outbox(outbox_id, claim_token, now):
    try:
        outbox = EmailOutbox.objects.select_for_update().get(pk=outbox_id)
    except EmailOutbox.DoesNotExist as exc:
        raise OutboxClaimLost("Email outbox item no longer exists.") from exc
    if not _owns_claim(outbox, claim_token, now):
        raise OutboxClaimLost("Email outbox claim is no longer valid.")
    return outbox


def release_email_outbox_claim(
    *, outbox_id, claim_token, code="WORKER_INTERRUPTED", delay_seconds=30
):
    """Return an owned claim to the queue without consuming an attempt."""
    now = timezone.now()
    with transaction.atomic():
        outbox = _load_owned_outbox(outbox_id, claim_token, now)
        outbox.status = EmailOutbox.Status.RETRY
        outbox.available_at = now + timedelta(seconds=max(1, delay_seconds))
        outbox.last_error_code = (code or "WORKER_INTERRUPTED")[:64]
        outbox.last_error_at = now
        _clear_claim(outbox)
        outbox.save(
            update_fields=[
                "status",
                "available_at",
                "last_error_code",
                "last_error_at",
                "claim_token",
                "claimed_at",
                "lease_expires_at",
                "updated_at",
            ]
        )


def _render_retry_delay(render_failure_count):
    return min(
        RENDER_RETRY_MAX_SECONDS,
        RENDER_RETRY_BASE_SECONDS * (2 ** max(0, render_failure_count - 1)),
    )


def record_email_outbox_render_failure(
    *,
    outbox_id,
    claim_token,
    now=None,
):
    """Record one owned generic render failure without using provider budget."""
    now = now or timezone.now()
    with transaction.atomic():
        outbox = _load_owned_outbox(outbox_id, claim_token, now)
        outbox.render_failure_count += 1

        if outbox.render_failure_count >= MAX_RENDER_FAILURES:
            _set_terminal(
                outbox,
                status=EmailOutbox.Status.DEAD,
                code=OUTBOX_RENDER_RETRY_EXHAUSTED,
                now=now,
                extra_update_fields=("render_failure_count",),
            )
            return "dead"

        outbox.status = EmailOutbox.Status.RETRY
        outbox.available_at = now + timedelta(
            seconds=_render_retry_delay(outbox.render_failure_count)
        )
        outbox.last_error_code = "WORKER_UNEXPECTED_ERROR"
        outbox.last_error_at = now
        _clear_claim(outbox)
        outbox.save(
            update_fields=[
                "status",
                "render_failure_count",
                "available_at",
                "last_error_code",
                "last_error_at",
                "claim_token",
                "claimed_at",
                "lease_expires_at",
                "updated_at",
            ]
        )
        return "retry"


def reset_email_outbox_render_failure_count(
    *,
    outbox_id,
    claim_token,
    now=None,
):
    """Reset an owned consecutive render-failure sequence after success."""
    now = now or timezone.now()
    with transaction.atomic():
        outbox = _load_owned_outbox(outbox_id, claim_token, now)
        if outbox.render_failure_count == 0:
            return False
        outbox.render_failure_count = 0
        outbox.save(update_fields=["render_failure_count", "updated_at"])
        return True


def cancel_email_outbox_claim(*, outbox_id, claim_token, code, now=None):
    """Cancel an owned claim without creating a delivery or using an attempt."""
    now = now or timezone.now()
    with transaction.atomic():
        outbox = _load_owned_outbox(outbox_id, claim_token, now)
        _set_terminal(
            outbox,
            status=EmailOutbox.Status.CANCELLED,
            code=code or "OUTBOX_CANCELLED",
            now=now,
        )


def mark_email_outbox_permanent_failure(
    *, outbox_id, claim_token, error_code, now=None
):
    """Dead-letter one owned poison item without changing delivery history."""
    now = now or timezone.now()
    safe_error = OutboxPermanentItemError(error_code)
    with transaction.atomic():
        outbox = _load_owned_outbox(outbox_id, claim_token, now)
        _set_terminal(
            outbox,
            status=EmailOutbox.Status.DEAD,
            code=safe_error.code,
            now=now,
        )


def purge_cancelled_password_reset_noops(
    *,
    now=None,
    batch_size=PASSWORD_RESET_NOOP_CLEANUP_BATCH_SIZE,
):
    """Delete a bounded batch of expired noop intents without delivery audits."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive.")
    now = now or timezone.now()
    cutoff = now - PASSWORD_RESET_NOOP_RETENTION
    noop_filter = Q(
        kind=EmailOutbox.Kind.PASSWORD_RESET,
        status=EmailOutbox.Status.CANCELLED,
        recipient_user__isnull=True,
        completed_at__lt=cutoff,
    )
    outbox_ids = list(
        EmailOutbox.objects.filter(noop_filter)
        .order_by("completed_at", "pk")
        .values_list("pk", flat=True)[:batch_size]
    )
    if not outbox_ids:
        return 0
    deleted, _details = EmailOutbox.objects.filter(
        noop_filter,
        pk__in=outbox_ids,
    ).delete()
    return deleted


def _render_password_reset(outbox):
    from accounts.password_reset import render_password_reset_outbox

    return render_password_reset_outbox(outbox)


def _render_email_verification(outbox):
    from accounts.email_verification import render_email_verification_outbox

    return render_email_verification_outbox(outbox)


def _render_notification(outbox):
    from .transactional_email import render_notification_outbox

    return render_notification_outbox(outbox)


OUTBOX_RENDERERS = {
    EmailOutbox.Kind.PASSWORD_RESET: _render_password_reset,
    EmailOutbox.Kind.EMAIL_VERIFICATION: _render_email_verification,
    EmailOutbox.Kind.NOTIFICATION: _render_notification,
}


def render_outbox_email(outbox):
    try:
        renderer = OUTBOX_RENDERERS[outbox.kind]
    except KeyError:
        raise OutboxRendererUnavailable(
            "No outbox renderer is installed for this kind."
        ) from None
    try:
        return renderer(outbox)
    except (TemplateDoesNotExist, TemplateSyntaxError):
        raise OutboxConfigurationError(
            "Required email templates are unavailable."
        ) from None


def _business_cancellation_code(outbox, now):
    if outbox.kind == EmailOutbox.Kind.PASSWORD_RESET:
        from accounts.password_reset import password_reset_cancellation_code

        return password_reset_cancellation_code(outbox, now=now)
    if outbox.kind == EmailOutbox.Kind.EMAIL_VERIFICATION:
        from accounts.email_verification import email_verification_cancellation_code

        return email_verification_cancellation_code(outbox, now=now)
    if outbox.kind == EmailOutbox.Kind.NOTIFICATION:
        from .transactional_email import notification_cancellation_code

        return notification_cancellation_code(outbox)
    return None


def _validate_payload(payload):
    return EmailPayload(
        recipient_email=_validate_recipient(payload.recipient_email),
        subject=_required(payload.subject, "Email subject"),
        html_body=_required(payload.html_body, "Email HTML body"),
        text_body=_required(payload.text_body, "Email text body"),
        from_email=_required(payload.from_email, "From email"),
        reply_to=_required(payload.reply_to, "Reply-To email"),
    )


def _prepare_dispatch(*, outbox_id, claim_token, payload, now):
    payload_digest = canonical_payload_hash(payload)

    with transaction.atomic():
        outbox = _load_owned_outbox(outbox_id, claim_token, now)

        cancellation_code = _business_cancellation_code(outbox, now)
        if cancellation_code:
            _set_terminal(
                outbox,
                status=EmailOutbox.Status.CANCELLED,
                code=cancellation_code,
                now=now,
            )
            return outbox, None, "cancelled", None

        if outbox.expires_at is not None and outbox.expires_at <= now:
            _set_terminal(
                outbox,
                status=EmailOutbox.Status.CANCELLED,
                code="OUTBOX_EXPIRED",
                now=now,
            )
            return outbox, None, "cancelled", None

        if outbox.recipient_hash != build_recipient_hash(payload.recipient_email):
            _set_terminal(
                outbox,
                status=EmailOutbox.Status.CANCELLED,
                code="RECIPIENT_CHANGED",
                now=now,
            )
            return outbox, None, "cancelled", None

        _validate_outbox_provider(outbox.provider)

        if outbox.payload_hash and outbox.payload_hash != payload_digest:
            _set_terminal(
                outbox,
                status=EmailOutbox.Status.DEAD,
                code="PAYLOAD_HASH_MISMATCH",
                now=now,
            )
            return outbox, None, "dead", None

        if outbox.attempt_count >= outbox.max_attempts:
            _set_terminal(
                outbox,
                status=EmailOutbox.Status.DEAD,
                code="MAX_ATTEMPTS_EXCEEDED",
                now=now,
            )
            return outbox, None, "dead", None

        if (
            outbox.provider_retry_deadline_at is not None
            and outbox.provider_retry_deadline_at <= now
        ):
            _set_terminal(
                outbox,
                status=EmailOutbox.Status.DEAD,
                code="PROVIDER_RETRY_DEADLINE_EXCEEDED",
                now=now,
            )
            return outbox, None, "dead", None

        delivery = (
            EmailDelivery.objects.select_for_update()
            .filter(outbox=outbox)
            .first()
        )
        if delivery is not None and (
            delivery.idempotency_key != outbox.provider_idempotency_key
            or delivery.provider != outbox.provider
            or delivery.recipient_hash != outbox.recipient_hash
        ):
            _set_terminal(
                outbox,
                status=EmailOutbox.Status.DEAD,
                code="DELIVERY_INVARIANT_MISMATCH",
                now=now,
            )
            return outbox, None, "dead", None

        conflicting_delivery = None
        if delivery is None:
            conflicting_delivery = EmailDelivery.objects.filter(
                idempotency_key=outbox.provider_idempotency_key
            ).first()
        if conflicting_delivery is not None:
            _set_terminal(
                outbox,
                status=EmailOutbox.Status.DEAD,
                code="DELIVERY_OWNERSHIP_CONFLICT",
                now=now,
            )
            return outbox, None, "dead", None

        if delivery is not None and delivery.status == EmailDelivery.Status.SENT:
            _set_terminal(
                outbox,
                status=EmailOutbox.Status.SENT,
                code="",
                now=now,
            )
            return outbox, delivery, "sent", None

        preparation = DispatchPreparation(
            previous_attempt_count=outbox.attempt_count,
            previous_first_attempt_at=outbox.first_attempt_at,
            previous_provider_retry_deadline_at=outbox.provider_retry_deadline_at,
            prepared_attempt_count=outbox.attempt_count + 1,
        )

        if delivery is None:
            delivery = EmailDelivery.objects.create(
                outbox=outbox,
                notification=outbox.notification,
                provider=outbox.provider,
                idempotency_key=outbox.provider_idempotency_key,
                recipient_hash=outbox.recipient_hash,
                status=EmailDelivery.Status.PENDING,
                attempt_count=1,
            )
        else:
            # A valid outbox lease, not EmailDelivery.PENDING itself, grants
            # authority to resume an interrupted outbox-owned dispatch.
            delivery.provider = outbox.provider
            delivery.status = EmailDelivery.Status.PENDING
            delivery.attempt_count += 1
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

        if not outbox.payload_hash:
            outbox.payload_hash = payload_digest
        if outbox.first_attempt_at is None:
            outbox.first_attempt_at = now
            outbox.provider_retry_deadline_at = now + PROVIDER_RETRY_WINDOW
        outbox.attempt_count += 1
        outbox.save(
            update_fields=[
                "payload_hash",
                "first_attempt_at",
                "provider_retry_deadline_at",
                "attempt_count",
                "updated_at",
            ]
        )
        return outbox, delivery, "dispatch", preparation


def _rollback_global_provider_attempt(
    *, outbox_id, claim_token, preparation, now
):
    """Restore the retry budget for an owned global provider failure."""
    with transaction.atomic():
        outbox = _load_owned_outbox(outbox_id, claim_token, now)
        if outbox.attempt_count != preparation.prepared_attempt_count:
            raise OutboxClaimLost("Email outbox dispatch state has changed.")

        outbox.attempt_count = preparation.previous_attempt_count
        outbox.first_attempt_at = preparation.previous_first_attempt_at
        outbox.provider_retry_deadline_at = (
            preparation.previous_provider_retry_deadline_at
        )
        outbox.save(
            update_fields=[
                "attempt_count",
                "first_attempt_at",
                "provider_retry_deadline_at",
                "updated_at",
            ]
        )


def _retry_delay(attempt_count, retry_after_seconds=None):
    if retry_after_seconds is not None:
        try:
            retry_after = float(retry_after_seconds)
        except (TypeError, ValueError):
            retry_after = None
        if retry_after is not None:
            return max(1.0, min(retry_after, MAX_BACKOFF_SECONDS))
    ceiling = min(MAX_BACKOFF_SECONDS, 30 * (2 ** max(0, attempt_count - 1)))
    return random.uniform(max(1, ceiling / 2), ceiling)


def _finalize_failure(*, outbox_id, claim_token, error, now):
    with transaction.atomic():
        outbox = _load_owned_outbox(outbox_id, claim_token, now)
        delivery = EmailDelivery.objects.select_for_update().get(outbox=outbox)
        code = (getattr(error, "code", "provider_transport_unknown") or "")[:64]
        delivery.status = EmailDelivery.Status.FAILED
        delivery.last_error_type = code[:128]
        delivery.sent_at = None
        delivery.save(
            update_fields=["status", "last_error_type", "sent_at", "updated_at"]
        )

        retryable = bool(getattr(error, "retryable", True))
        delay = _retry_delay(
            outbox.attempt_count,
            getattr(error, "retry_after_seconds", None),
        )
        available_at = now + timedelta(seconds=delay)
        deadline_exceeded = (
            outbox.provider_retry_deadline_at is not None
            and available_at >= outbox.provider_retry_deadline_at
        )
        exhausted = outbox.attempt_count >= outbox.max_attempts

        if not retryable or deadline_exceeded or exhausted:
            terminal_code = code
            if exhausted:
                terminal_code = "MAX_ATTEMPTS_EXCEEDED"
            elif deadline_exceeded:
                terminal_code = "PROVIDER_RETRY_DEADLINE_EXCEEDED"
            _set_terminal(
                outbox,
                status=EmailOutbox.Status.DEAD,
                code=terminal_code,
                now=now,
            )
            return "dead"

        outbox.status = EmailOutbox.Status.RETRY
        outbox.available_at = available_at
        outbox.last_error_code = code
        outbox.last_error_at = now
        _clear_claim(outbox)
        outbox.save(
            update_fields=[
                "status",
                "available_at",
                "last_error_code",
                "last_error_at",
                "claim_token",
                "claimed_at",
                "lease_expires_at",
                "updated_at",
            ]
        )
        return "retry"


def _finalize_success(*, outbox_id, claim_token, provider_message_id, now):
    provider_message_id = validate_provider_message_id(provider_message_id)
    with transaction.atomic():
        outbox = _load_owned_outbox(outbox_id, claim_token, now)
        delivery = EmailDelivery.objects.select_for_update().get(outbox=outbox)
        delivery.status = EmailDelivery.Status.SENT
        delivery.provider_message_id = provider_message_id
        delivery.last_error_type = ""
        delivery.sent_at = now
        try:
            delivery.save(
                update_fields=[
                    "status",
                    "provider_message_id",
                    "last_error_type",
                    "sent_at",
                    "updated_at",
                ]
            )
        except IntegrityError:
            logger.error(
                "Email provider message ownership conflict: "
                "outbox_id=%s delivery_id=%s error_code=%s",
                outbox_id,
                delivery.pk,
                OUTBOX_PROVIDER_MESSAGE_OWNERSHIP_CONFLICT,
            )
            raise OutboxPermanentItemError(
                OUTBOX_PROVIDER_MESSAGE_OWNERSHIP_CONFLICT
            ) from None
        _set_terminal(
            outbox,
            status=EmailOutbox.Status.SENT,
            code="",
            now=now,
        )

    try:
        from .webhook_service import reconcile_unmatched_resend_events

        reconcile_unmatched_resend_events(provider_message_id)
    except Exception as exc:
        logger.warning(
            "Email webhook reconciliation failed: outbox_id=%s exception_type=%s",
            outbox_id,
            exc.__class__.__name__,
        )


def _send_with_provider(outbox, payload):
    if outbox.provider != "resend":
        raise OutboxPermanentItemError(OUTBOX_PROVIDER_MISMATCH)
    try:
        provider = ResendProvider(
            api_key=getattr(settings, "RESEND_API_KEY", ""),
            timeout_seconds=getattr(settings, "RESEND_TIMEOUT_SECONDS", 30),
        )
        return provider.send(
            recipient_email=payload.recipient_email,
            subject=payload.subject,
            html_body=payload.html_body,
            text_body=payload.text_body,
            from_email=payload.from_email,
            reply_to=payload.reply_to,
            idempotency_key=outbox.provider_idempotency_key,
        )
    except ResendConfigurationError as exc:
        raise OutboxConfigurationError("Resend is not configured.") from exc


def send_outbox_email(*, outbox_id, claim_token, payload, now=None):
    """Dispatch one claimed outbox item without holding a DB transaction."""
    now = now or timezone.now()
    validate_dispatch_configuration()
    try:
        (
            EmailOutbox.objects.filter(
                pk=outbox_id,
                status=EmailOutbox.Status.PROCESSING,
                claim_token=claim_token,
                lease_expires_at__gt=now,
            )
            .values_list("pk", flat=True)
            .get()
        )
    except EmailOutbox.DoesNotExist as exc:
        raise OutboxClaimLost(
            "Email outbox item is missing or the claim is no longer valid."
        ) from exc
    payload = _validate_payload(payload)
    outbox, delivery, action, preparation = _prepare_dispatch(
        outbox_id=outbox_id,
        claim_token=claim_token,
        payload=payload,
        now=now,
    )

    if action != "dispatch":
        return EmailSendResult(
            provider=outbox.provider,
            status=action,
            provider_message_id=(
                delivery.provider_message_id if delivery is not None else None
            ),
            idempotency_key=outbox.provider_idempotency_key,
        )

    try:
        provider_message_id = _send_with_provider(outbox, payload)
    except OutboxConfigurationError:
        # Startup validation normally prevents this. Keep the claimed item
        # recoverable instead of consuming/dead-lettering it on global config.
        _rollback_global_provider_attempt(
            outbox_id=outbox.pk,
            claim_token=claim_token,
            preparation=preparation,
            now=timezone.now(),
        )
        raise
    except ResendDeliveryError as exc:
        if getattr(exc, "global_problem", False):
            _rollback_global_provider_attempt(
                outbox_id=outbox.pk,
                claim_token=claim_token,
                preparation=preparation,
                now=timezone.now(),
            )
            raise OutboxConfigurationError(
                "Email provider global configuration failed."
            ) from exc
        status = _finalize_failure(
            outbox_id=outbox.pk,
            claim_token=claim_token,
            error=exc,
            now=timezone.now(),
        )
        return EmailSendResult(
            provider=outbox.provider,
            status=status,
            idempotency_key=outbox.provider_idempotency_key,
        )

    _finalize_success(
        outbox_id=outbox.pk,
        claim_token=claim_token,
        provider_message_id=provider_message_id,
        now=timezone.now(),
    )
    return EmailSendResult(
        provider=outbox.provider,
        status="sent",
        provider_message_id=provider_message_id,
        idempotency_key=outbox.provider_idempotency_key,
    )
