import logging

from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string

from .email_policy import notification_email_policy
from .email_service import EmailServiceError, send_email
from .models import Notification


logger = logging.getLogger(__name__)


class TransactionalEmailConfigurationError(RuntimeError):
    """Raised when transactional notification email configuration is invalid."""


def _site_base_url() -> str:
    base_url = (
        getattr(settings, "SITE_BASE_URL", "")
        or ""
    ).strip().rstrip("/")

    if not base_url:
        raise TransactionalEmailConfigurationError(
            "SITE_BASE_URL is required for transactional notification emails."
        )

    return base_url


def build_notification_target_url(notification: Notification) -> str:
    path = notification.target_url

    if not path.startswith("/"):
        raise TransactionalEmailConfigurationError(
            "Notification target must be an internal absolute path."
        )

    return f"{_site_base_url()}{path}"


def _subject(notification: Notification) -> str:
    title = (notification.title or "").strip().rstrip(".")
    return f"{title} | DertDerman"


def deliver_notification_email(notification: Notification):
    decision = notification_email_policy(notification)

    if not decision.should_send:
        return None

    target_url = build_notification_target_url(notification)

    context = {
        "notification": notification,
        "recipient": notification.recipient_user,
        "category_label": decision.category_label,
        "cta_label": decision.cta_label,
        "accent": decision.accent,
        "target_url": target_url,
        "support_email": getattr(
            settings,
            "SUPPORT_EMAIL",
            "destek@dertderman.com",
        ),
        "support_phone": getattr(
            settings,
            "SUPPORT_PHONE",
            "+90 850 532 2206",
        ),
        "support_hours": getattr(
            settings,
            "SUPPORT_HOURS",
            "Hafta içi 09:00 - 18:00",
        ),
    }

    html_body = render_to_string(
        "emails/transactional_notification.html",
        context,
    )
    text_body = render_to_string(
        "emails/transactional_notification.txt",
        context,
    )

    email_event_key = (
        "notification-email:"
        f"{notification.recipient_user_id}:"
        f"{notification.event_key}"
    )

    return send_email(
        recipient_email=notification.recipient_user.email,
        subject=_subject(notification),
        html_body=html_body,
        text_body=text_body,
        event_key=email_event_key,
    )


def _load_notification(notification_id: int) -> Notification | None:
    return (
        Notification.objects
        .select_related(
            "recipient_user",
            "complaint",
            "company",
            "content_report",
            "user_report",
            "company_report",
            "abuse_attempt",
        )
        .filter(pk=notification_id)
        .first()
    )


def _safe_deliver(notification_id: int) -> None:
    notification = _load_notification(notification_id)

    if notification is None:
        return

    try:
        deliver_notification_email(notification)
    except EmailServiceError as exc:
        logger.warning(
            "Transactional email delivery failed: "
            "notification_id=%s exception_type=%s",
            notification_id,
            exc.__class__.__name__,
        )
    except Exception as exc:
        logger.error(
            "Transactional email processing failed: "
            "notification_id=%s exception_type=%s",
            notification_id,
            exc.__class__.__name__,
        )


def schedule_notification_email(notification: Notification) -> None:
    if not notification_email_policy(notification).should_send:
        return

    notification_id = notification.pk

    transaction.on_commit(
        lambda: _safe_deliver(notification_id)
    )
