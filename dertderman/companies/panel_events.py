from uuid import uuid4

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from complaints.models import Complaint

from .models import Company, CompanyNotification


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


@transaction.atomic
def record_complaint_notification(
    complaint,
    kind,
    event_key=None,
    notify_user=True,
):
    from notifications.services import complaint_event

    # Her durum geçişi için deterministik bir bildirim anahtarı oluşturulur.
    event_key = event_key or (
        f"complaint:{complaint.pk}:{kind}:"
        f"{complaint.updated_at.isoformat()}"
    )

    if kind == CompanyNotification.Kind.REMOVED:
        reason = _violation_reason_label(complaint)

        title = "Bir şikayet moderasyon kararıyla kaldırıldı."

        message = (
            f'"{complaint.title}" başlıklı şikayet, '
            "topluluk kurallarını ihlal ettiği için yayından kaldırıldı. "
            f"Kaldırılma nedeni: {reason}."
        )

    else:
        title = CompanyNotification.Kind(kind).label

        message = (
            "Şikayetle ilgili gelişmeyi çalışma alanınızdan "
            "inceleyebilirsiniz."
        )

    notification, _ = CompanyNotification.objects.get_or_create(
        event_key=event_key,
        defaults={
            "company_id": complaint.company_id,
            "complaint": complaint,
            "kind": kind,
            "title": title,
            "message": message,
        },
    )

    if notify_user:
        complaint_event(
            complaint,
            kind,
            event_key,
        )

    return notification


@receiver(pre_save, sender=Complaint)
def capture_complaint_state(
    sender,
    instance,
    raw=False,
    **kwargs,
):
    if not raw:
        instance._company_panel_previous = (
            sender.objects.filter(
                pk=instance.pk,
            )
            .values(
                "status",
                "title",
                "description",
            )
            .first()
            if instance.pk
            else None
        )


@receiver(post_save, sender=Complaint)
def notify_company_of_complaint(
    sender,
    instance,
    created,
    raw=False,
    **kwargs,
):
    if raw:
        return

    previous = getattr(
        instance,
        "_company_panel_previous",
        None,
    )

    # update_fields kullanılmışsa kaydın güncel halini tekrar al.
    fields = kwargs.get("update_fields")

    if fields is not None:
        instance = sender.objects.get(
            pk=instance.pk,
        )

    kind = None

    if created:
        kind = CompanyNotification.Kind.NEW

    elif previous and previous["status"] != instance.status:
        kind = {
            Complaint.Status.PUBLISHED:
                CompanyNotification.Kind.PUBLISHED,

            Complaint.Status.RESOLVED:
                CompanyNotification.Kind.RESOLVED,

            Complaint.Status.REMOVED:
                CompanyNotification.Kind.REMOVED,

        }.get(
            instance.status,
            CompanyNotification.Kind.ADMIN,
        )

    elif previous and any(
        previous[field] != getattr(instance, field)
        for field in (
            "title",
            "description",
        )
    ):
        kind = CompanyNotification.Kind.UPDATED

    if kind:
        key = (
            f"complaint:{instance.pk}:{kind}:{uuid4()}"
            if (
                fields is not None
                and "updated_at" not in fields
            )
            else None
        )

        record_complaint_notification(
            instance,
            kind,
            event_key=key,
        )


@receiver(pre_save, sender=Company)
def capture_company_state(
    sender,
    instance,
    raw=False,
    **kwargs,
):
    if not raw:
        instance._panel_approval_previous = (
            sender.objects.filter(
                pk=instance.pk,
            )
            .values(
                "approval_status",
                "is_verified",
                "is_active",
            )
            .first()
            if instance.pk
            else None
        )


@receiver(post_save, sender=Company)
def notify_company_of_admin_action(
    sender,
    instance,
    created,
    raw=False,
    **kwargs,
):
    previous = getattr(
        instance,
        "_panel_approval_previous",
        None,
    )

    if (
        not raw
        and not created
        and kwargs.get("update_fields") is not None
    ):
        instance = sender.objects.get(
            pk=instance.pk,
        )

    if (
        not raw
        and not created
        and previous
        and any(
            previous[key] != getattr(instance, key)
            for key in previous
        )
    ):
        title = (
            "Şirketinizin onay veya doğrulama durumu güncellendi."
        )

        if (
            previous["approval_status"] == "PENDING"
            and instance.approval_status != "PENDING"
        ):
            title = (
                "Şirket başvurunuz onaylandı."
                if instance.approval_status == "APPROVED"
                else "Şirket başvurunuz reddedildi."
            )

        CompanyNotification.objects.get_or_create(
            event_key=f"company:{instance.pk}:{uuid4()}",
            defaults={
                "company": instance,
                "kind": CompanyNotification.Kind.ADMIN,
                "title": title,
                "message": (
                    "Güncel şirket bilgilerinizi "
                    "profilinizden inceleyebilirsiniz."
                ),
            },
        )