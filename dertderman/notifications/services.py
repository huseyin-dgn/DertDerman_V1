from django.utils import timezone

from accounts.models import User

from .models import Notification


def send(
    *,
    recipient,
    scope,
    kind,
    event_key,
    title,
    message="",
    complaint=None,
    company=None,
):
    if not recipient.is_active or recipient.user_type != scope:
        return None

    notification, _ = Notification.objects.get_or_create(
        recipient_user=recipient,
        recipient_role=scope,
        event_key=event_key,
        defaults={
            "notification_type": kind,
            "title": title,
            "message": message,
            "complaint": complaint,
            "company": None if complaint else company,
        },
    )

    return notification


def send_admins(**event):
    for admin in User.objects.filter(
        user_type="ADMIN",
        is_active=True,
    ).iterator():
        send(
            recipient=admin,
            scope="ADMIN",
            **event,
        )


def complaint_social_event(
    *,
    complaint,
    actor,
    kind,
    event_key,
):
    """
    Şikayet sahibini sosyal etkileşimlerden haberdar eder.
    Kullanıcının kendi yaptığı işlem için bildirim oluşturmaz.
    """

    if actor.pk == complaint.user_id:
        return None

    mapping = {
        "LIKE": (
            "Şikayetiniz beğenildi.",
            "Bir kullanıcı deneyiminizi faydalı buldu.",
        ),
        "REACTION": (
            "Şikayetinize bir kullanıcı tepki verdi.",
            "Topluluktan yeni bir tepki aldınız.",
        ),
        "COMMENT": (
            "Şikayetinize yeni bir yorum yapıldı.",
            "Yeni yorumu şikayet detayında inceleyebilirsiniz.",
        ),
    }

    if kind not in mapping:
        return None

    title, message = mapping[kind]

    return send(
        recipient=complaint.user,
        scope="USER",
        kind=kind,
        event_key=event_key,
        title=title,
        message=message,
        complaint=complaint,
        company=complaint.company,
    )


def _violation_reason_label(complaint):
    reason_mapping = {
        "SPAM": "Spam / reklam",
        "HARASSMENT": "Taciz veya rahatsız edici içerik",
        "HATE": "Nefret söylemi",
        "PERSONAL_DATA": "Kişisel veri ihlali",
        "MISLEADING": "Yanıltıcı içerik",
        "ILLEGAL": "Yasa dışı içerik",
        "OTHER": "Diğer",
    }

    return reason_mapping.get(
        complaint.violation_reason,
        "Topluluk kuralları ihlali",
    )


def complaint_event(
    complaint,
    kind,
    event_key,
):
    """
    Şikayet durum değişikliklerinde şikayet sahibine bildirim gönderir.
    """

    if kind == "REMOVED":
        reason = _violation_reason_label(complaint)

        return send(
            recipient=complaint.user,
            scope="USER",
            kind=Notification.Type.REMOVED,
            event_key=event_key,
            title="Şikayetiniz yayından kaldırıldı.",
            message=(
                "Şikayetiniz topluluk kurallarını ihlal ettiği için "
                f"yayından kaldırıldı. Kaldırılma nedeni: {reason}."
            ),
            complaint=complaint,
            company=complaint.company,
        )

    mapping = {
        "NEW": (
            "RECEIVED",
            "Şikayetiniz alındı.",
            "Şikayetiniz yayınlanmadan önce yönetim tarafından incelenecek.",
        ),

        "PUBLISHED": (
            Notification.Type.PUBLISHED,
            "Şikayetiniz yayınlandı.",
            "Şikayetinizin durumunu kişisel alanınızdan takip edebilirsiniz.",
        ),

        "RESOLVED": (
            Notification.Type.RESOLVED,
            "Şikayetiniz çözüldü.",
            "Şikayetiniz çözülmüş olarak güncellendi.",
        ),

        "ADMIN": (
            Notification.Type.REJECTED,
            "Şikayetiniz reddedildi.",
            "Şikayetinizin yayın başvurusu kabul edilmedi.",
        )
        if complaint.status == "REJECTED"
        else (
            "UPDATED",
            "Şikayetinizin durumu güncellendi.",
            "Güncel durumu kişisel alanınızdan inceleyebilirsiniz.",
        ),
    }

    if kind in mapping:
        notification_type, title, message = mapping[kind]

        send(
            recipient=complaint.user,
            scope="USER",
            kind=notification_type,
            event_key=event_key,
            title=title,
            message=message,
            complaint=complaint,
            company=complaint.company,
        )

    if kind == "NEW" and complaint.status == "PENDING":
        send_admins(
            kind="MODERATION",
            event_key=event_key,
            title="Yeni şikayet moderasyon bekliyor.",
            message=complaint.title,
            complaint=complaint,
            company=complaint.company,
        )


def mark_read(queryset):
    return queryset.filter(
        is_read=False,
    ).update(
        is_read=True,
        read_at=timezone.now(),
    )