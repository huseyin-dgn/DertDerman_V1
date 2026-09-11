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
    content_report=None,
    user_report=None,
    company_report=None,
    abuse_attempt=None,
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
            "content_report": content_report,
            "user_report": user_report,
            "company_report": company_report,
            "abuse_attempt": abuse_attempt,
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


def notify_admins_content_report(report):
    if report.target_type == "COMPLAINT":
        title = "Yeni şikayet raporu"

        message = (
            f'"{report.complaint.title}" başlıklı şikayet '
            f"{report.get_reason_display()} nedeniyle raporlandı."
        )

    else:
        title = "Yeni yorum raporu"

        message = (
            f"Bir yorum {report.get_reason_display()} "
            "nedeniyle raporlandı."
        )

    send_admins(
        kind=Notification.Type.CONTENT_REPORT,
        event_key=f"content-report:{report.pk}:created",
        title=title,
        message=message,
        content_report=report,
    )


def notify_admins_user_report(report):
    send_admins(
        kind=Notification.Type.USER_REPORT,
        event_key=f"user-report:{report.pk}:created",
        title="Yeni kullanıcı raporu",
        message=(
            f"@{report.reported_user.username} kullanıcısı "
            f"{report.get_reason_display()} nedeniyle raporlandı."
        ),
        user_report=report,
    )




def notify_admins_company_report(report):
    send_admins(
        kind=Notification.Type.COMPANY_REPORT,
        event_key=f"company-report:{report.pk}:created",
        title="Yeni şirket raporu",
        message=(
            f"{report.company.name} şirketi "
            f"{report.get_reason_display()} nedeniyle raporlandı."
        ),
        company_report=report,
    )


def notify_company_report_decision(report):
    if report.status == "REJECTED":
        return send(
            recipient=report.reporter,
            scope="USER",
            kind=Notification.Type.COMPANY_REPORT,
            event_key=f"company-report:{report.pk}:rejected",
            title="Şirket raporunuz sonuçlandırıldı.",
            message=(
                "Yönetim incelemesinde raporlanan şirket için "
                "doğrulanmış bir ihlal bulunmadı."
            ),
            company_report=report,
        )

    if report.status == "RESOLVED":
        return send(
            recipient=report.reporter,
            scope="USER",
            kind=Notification.Type.COMPANY_REPORT,
            event_key=f"company-report:{report.pk}:resolved",
            title="Şirket raporunuz sonuçlandırıldı.",
            message="Gönderdiğiniz şirket raporunda ihlal tespit edildi.",
            company_report=report,
        )

    if report.status == "ABUSIVE":
        return send(
            recipient=report.reporter,
            scope="USER",
            kind=Notification.Type.COMPANY_REPORT,
            event_key=f"company-report:{report.pk}:abusive",
            title="Şirket raporunuz kötüye kullanım olarak değerlendirildi.",
            message=(
                "Gönderdiğiniz şirket raporunun kötü niyetli veya asılsız "
                "olduğu tespit edildi. Hesabınıza doğrulanmış kötüye kullanım "
                "ihlali eklendi."
            ),
            company_report=report,
        )

    return None


def notify_admins_abuse_attempt(attempt):
    from datetime import timedelta
    from core.models import AbuseAttempt

    user = attempt.user
    if not user:
        return None

    immediate_events = {
        AbuseAttempt.EventType.COMPLAINT_RATE_LIMIT_10M,
        AbuseAttempt.EventType.COMPLAINT_RATE_LIMIT_1H,
        AbuseAttempt.EventType.COMPLAINT_RATE_LIMIT_24H,
        AbuseAttempt.EventType.NEW_ACCOUNT_LIMIT,
        AbuseAttempt.EventType.REJECTION_RESTRICTION,
        AbuseAttempt.EventType.IP_ABUSE_BLOCK,
    }

    repeated_content_events = {
        AbuseAttempt.EventType.DUPLICATE_COMPLAINT,
        AbuseAttempt.EventType.SIMILAR_COMPLAINT,
    }

    if attempt.event_type in immediate_events:
        bucket = attempt.created_at.strftime("%Y%m%d%H")
        send_admins(
            kind=Notification.Type.ABUSE_ALERT,
            event_key=f"abuse:{user.pk}:{attempt.event_type}:{bucket}",
            title="Güvenlik kısıtı tetiklendi",
            message=(
                f"@{user.username} kullanıcısı "
                f"{attempt.get_event_type_display()} kuralına takıldı. "
                "İşlem engellendi."
            ),
            abuse_attempt=attempt,
        )
        return None

    if attempt.event_type in repeated_content_events:
        since = attempt.created_at - timedelta(hours=24)
        repeat_count = (
            AbuseAttempt.objects
            .filter(
                user=user,
                event_type__in=repeated_content_events,
                created_at__gte=since,
            )
            .count()
        )

        if repeat_count < 3:
            return None

        day_bucket = attempt.created_at.strftime("%Y%m%d")
        send_admins(
            kind=Notification.Type.ABUSE_ALERT,
            event_key=f"abuse:{user.pk}:repeated-content:{day_bucket}",
            title="Tekrarlanan şikayet denemeleri",
            message=(
                f"@{user.username} kullanıcısının son 24 saatte "
                f"{repeat_count} adet aynı veya çok benzer şikayet "
                "gönderme denemesi engellendi."
            ),
            abuse_attempt=attempt,
        )

    return None



def notify_user_report_decision(report):
    if report.status == "RESOLVED":
        send(
            recipient=report.reported_user,
            scope="USER",
            kind=Notification.Type.USER_REPORT,
            event_key=f"user-report:{report.pk}:resolved:target",
            title="Hakkınızdaki kullanıcı raporu sonuçlandırıldı.",
            message=(
                "Yönetim incelemesi sonucunda topluluk kuralları ihlali "
                "doğrulandı ve hesabınıza ihlal kaydı eklendi."
            ),
            user_report=report,
        )

        send(
            recipient=report.reporter,
            scope="USER",
            kind=Notification.Type.USER_REPORT,
            event_key=f"user-report:{report.pk}:resolved:reporter",
            title="Kullanıcı raporunuz sonuçlandırıldı.",
            message=(
                "Gönderdiğiniz kullanıcı raporunda ihlal tespit edildi."
            ),
            user_report=report,
        )
        return None

    if report.status == "REJECTED":
        send(
            recipient=report.reporter,
            scope="USER",
            kind=Notification.Type.USER_REPORT,
            event_key=f"user-report:{report.pk}:rejected",
            title="Kullanıcı raporunuz sonuçlandırıldı.",
            message=(
                "Yönetim incelemesinde raporlanan kullanıcı için "
                "doğrulanmış bir ihlal bulunmadı."
            ),
            user_report=report,
        )
        return None

    if report.status == "ABUSIVE":
        send(
            recipient=report.reporter,
            scope="USER",
            kind=Notification.Type.USER_REPORT,
            event_key=f"user-report:{report.pk}:abusive",
            title="Raporunuz kötüye kullanım olarak değerlendirildi.",
            message=(
                "Gönderdiğiniz kullanıcı raporunun kötü niyetli veya "
                "asılsız olduğu tespit edildi. Hesabınıza doğrulanmış "
                "kötüye kullanım ihlali eklendi."
            ),
            user_report=report,
        )

    return None


def notify_account_suspended(user):
    return send(
        recipient=user,
        scope="USER",
        kind=Notification.Type.ACCOUNT_SUSPENDED,
        event_key=f"account:{user.pk}:suspended:{timezone.now().strftime('%Y%m%d%H%M%S')}",
        title="Hesabınız askıya alındı.",
        message=(
            user.suspension_reason
            or "Hesabınız yönetim kararıyla askıya alındı."
        ),
    )


def notify_account_restored(user):
    return send(
        recipient=user,
        scope="USER",
        kind=Notification.Type.ACCOUNT_RESTORED,
        event_key=f"account:{user.pk}:restored:{timezone.now().strftime('%Y%m%d%H%M%S')}",
        title="Hesabınızın askısı kaldırıldı.",
        message="Hesabınız yeniden işlem yapabilir durumdadır.",
    )


def mark_read(queryset):
    return queryset.filter(
        is_read=False,
    ).update(
        is_read=True,
        read_at=timezone.now(),
    )