from dataclasses import dataclass

from django.conf import settings

from accounts.models import User

from .models import Notification


EMAILABLE_USER_NOTIFICATION_TYPES = frozenset(
    {
        Notification.Type.PUBLISHED,
        Notification.Type.RESOLVED,
        Notification.Type.REJECTED,
        Notification.Type.REMOVED,
        Notification.Type.CONTENT_REPORT,
        Notification.Type.USER_REPORT,
        Notification.Type.COMPANY_REPORT,
        Notification.Type.ACCOUNT_SUSPENDED,
        Notification.Type.ACCOUNT_RESTORED,
        "RESPONSE",
        Notification.Type.COMPANY_RESPONDED,
    }
)


@dataclass(frozen=True)
class EmailPolicyDecision:
    should_send: bool
    category_label: str = ""
    cta_label: str = ""
    accent: str = "blue"


def _category_for(notification_type: str) -> tuple[str, str, str]:
    if notification_type in {
        Notification.Type.PUBLISHED,
        Notification.Type.RESOLVED,
        Notification.Type.REJECTED,
        Notification.Type.REMOVED,
    }:
        return "ŞİKAYET GÜNCELLEMESİ", "Şikayeti Görüntüle", "blue"

    if notification_type in {
        "RESPONSE",
        Notification.Type.COMPANY_RESPONDED,
    }:
        return "ŞİRKET YANITI", "Yanıtı Görüntüle", "blue"

    if notification_type in {
        Notification.Type.CONTENT_REPORT,
        Notification.Type.USER_REPORT,
        Notification.Type.COMPANY_REPORT,
    }:
        return "RAPOR SONUCU", "Detayları Görüntüle", "blue"

    if notification_type == Notification.Type.ACCOUNT_SUSPENDED:
        return "HESAP GÜVENLİĞİ", "Hesabımı Görüntüle", "warning"

    if notification_type == Notification.Type.ACCOUNT_RESTORED:
        return "HESAP GÜVENLİĞİ", "Hesabımı Görüntüle", "success"

    return "HESAP BİLDİRİMİ", "DertDerman'a Git", "blue"


def notification_email_policy(notification: Notification) -> EmailPolicyDecision:
    if not getattr(settings, "TRANSACTIONAL_EMAILS_ENABLED", True):
        return EmailPolicyDecision(False)

    if notification.recipient_role != Notification.Scope.USER:
        return EmailPolicyDecision(False)

    recipient = notification.recipient_user

    if (
        recipient.user_type != User.UserType.USER
        or not recipient.is_active
        or not recipient.is_verified
        or not (recipient.email or "").strip()
        or getattr(recipient, "is_permanently_closed", False)
    ):
        return EmailPolicyDecision(False)

    if notification.notification_type not in EMAILABLE_USER_NOTIFICATION_TYPES:
        return EmailPolicyDecision(False)

    category_label, cta_label, accent = _category_for(
        notification.notification_type
    )

    return EmailPolicyDecision(
        True,
        category_label=category_label,
        cta_label=cta_label,
        accent=accent,
    )
