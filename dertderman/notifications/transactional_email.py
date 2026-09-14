import uuid

from django.conf import settings
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .email_policy import notification_email_policy
from .email_service import build_recipient_hash
from .models import EmailOutbox, Notification
from .outbox_service import (
    EmailPayload,
    OUTBOX_INVALID_RECIPE,
    OUTBOX_UNSUPPORTED_TEMPLATE_VERSION,
    OutboxBusinessCancellation,
    OutboxConfigurationError,
    OutboxPermanentItemError,
)


NOTIFICATION_POLICY_CHANGED = "NOTIFICATION_POLICY_CHANGED"


class TransactionalEmailConfigurationError(OutboxConfigurationError):
    """Global notification-email rendering configuration is invalid."""


def _site_base_url() -> str:
    base_url = (getattr(settings, "SITE_BASE_URL", "") or "").strip().rstrip("/")
    if not base_url:
        raise TransactionalEmailConfigurationError(
            "SITE_BASE_URL is required for transactional notification emails."
        )
    return base_url


def _public_complaint_path(notification: Notification) -> str | None:
    complaint = notification.complaint
    if complaint is None:
        return None

    public_notification_types = {
        Notification.Type.PUBLISHED,
        Notification.Type.RESOLVED,
        "RESPONSE",
        Notification.Type.COMPANY_RESPONDED,
    }
    if notification.notification_type not in public_notification_types:
        return None
    if complaint.status not in {"PUBLISHED", "RESOLVED"}:
        return None
    if complaint.withdrawn_at is not None:
        return None
    if getattr(complaint, "removed_for_violation", False):
        return None
    if not complaint.company.is_active:
        return None
    return reverse("complaints:public_detail", args=[complaint.pk])


def build_notification_target_url(notification: Notification) -> str:
    path = _public_complaint_path(notification) or notification.target_url
    if not path.startswith("/"):
        raise OutboxPermanentItemError(OUTBOX_INVALID_RECIPE)
    return f"{_site_base_url()}{path}"


def _subject(notification: Notification) -> str:
    title = (notification.title or "").strip().rstrip(".")
    return f"{title} | DertDerman"


def enqueue_notification_email(notification: Notification):
    """Persist an email intent; the caller owns the surrounding transaction."""
    decision = notification_email_policy(notification)
    if not decision.should_send:
        return None

    outbox_id = uuid.uuid4()
    return EmailOutbox.objects.create(
        id=outbox_id,
        kind=EmailOutbox.Kind.NOTIFICATION,
        status=EmailOutbox.Status.PENDING,
        recipient_user=notification.recipient_user,
        notification=notification,
        recipient_hash=build_recipient_hash(notification.recipient_user.email),
        request_state_hash="",
        provider="resend",
        provider_idempotency_key=f"dertderman/email/{outbox_id}",
        template_version=1,
        token_issued_at=None,
        expires_at=None,
        available_at=timezone.now(),
    )


def _notification_for_outbox(outbox):
    if outbox.kind != EmailOutbox.Kind.NOTIFICATION:
        raise OutboxPermanentItemError(OUTBOX_INVALID_RECIPE)
    if outbox.notification_id is None or outbox.recipient_user_id is None:
        raise OutboxPermanentItemError(OUTBOX_INVALID_RECIPE)

    notification = (
        Notification.objects.select_related(
            "recipient_user",
            "complaint",
            "company",
            "content_report",
            "user_report",
            "company_report",
            "abuse_attempt",
        )
        .filter(pk=outbox.notification_id)
        .first()
    )
    if (
        notification is None
        or notification.recipient_user_id != outbox.recipient_user_id
        or not notification_email_policy(notification).should_send
    ):
        raise OutboxBusinessCancellation(NOTIFICATION_POLICY_CHANGED)
    return notification


def notification_cancellation_code(outbox):
    try:
        _notification_for_outbox(outbox)
    except OutboxBusinessCancellation as exc:
        return exc.code
    return None


def render_notification_outbox(outbox):
    notification = _notification_for_outbox(outbox)
    if outbox.template_version != 1:
        raise OutboxPermanentItemError(OUTBOX_UNSUPPORTED_TEMPLATE_VERSION)

    decision = notification_email_policy(notification)
    context = {
        "notification": notification,
        "recipient": notification.recipient_user,
        "category_label": decision.category_label,
        "cta_label": decision.cta_label,
        "accent": decision.accent,
        "target_url": build_notification_target_url(notification),
        "support_email": getattr(settings, "SUPPORT_EMAIL", "destek@dertderman.com"),
        "support_phone": getattr(settings, "SUPPORT_PHONE", "+90 850 532 2206"),
        "support_hours": getattr(
            settings,
            "SUPPORT_HOURS",
            "Hafta içi 09:00 - 18:00",
        ),
    }
    return EmailPayload(
        recipient_email=notification.recipient_user.email,
        subject=_subject(notification),
        html_body=render_to_string(
            "emails/transactional_notification.html", context
        ),
        text_body=render_to_string(
            "emails/transactional_notification.txt", context
        ),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", ""),
        reply_to=getattr(settings, "EMAIL_REPLY_TO", ""),
    )
