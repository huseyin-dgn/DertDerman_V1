from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Complaint, ComplaintEvent


EVENT_COPY = {
    ComplaintEvent.Type.CREATED: "Şikayetiniz oluşturuldu ve güvenle kaydedildi.",
    ComplaintEvent.Type.PENDING: "Şikayetiniz yayın öncesi inceleme sırasına alındı.",
    ComplaintEvent.Type.PUBLISHED: "Şikayetiniz incelemenin ardından yayınlandı.",
    ComplaintEvent.Type.REJECTED: "Şikayetiniz yayın incelemesi sonucunda reddedildi.",
    ComplaintEvent.Type.RESOLVED: "Şikayetiniz çözüldü olarak işaretlendi.",
    ComplaintEvent.Type.REMOVED: "Şikayetiniz topluluk kurallarını ihlal ettiği için yayından kaldırıldı.",
}


def record_event(
    complaint,
    event_type,
    *,
    actor_type=ComplaintEvent.Actor.SYSTEM,
    message=None,
    source_key,
    occurred_at=None,
):
    defaults = {
        "complaint": complaint,
        "event_type": event_type,
        "actor_type": actor_type,
        "message": message or EVENT_COPY[event_type],
    }

    if occurred_at is not None:
        defaults["occurred_at"] = occurred_at

    return ComplaintEvent.objects.get_or_create(
        source_key=source_key,
        defaults=defaults,
    )[0]


@receiver(pre_save, sender=Complaint)
def remember_status(sender, instance, raw=False, **kwargs):
    if not raw and instance.pk:
        instance._timeline_previous_status = (
            sender.objects
            .filter(pk=instance.pk)
            .values_list("status", flat=True)
            .first()
        )


@receiver(post_save, sender=Complaint)
def record_complaint_state(sender, instance, created, raw=False, **kwargs):
    if raw:
        return

    status_event_map = {
        Complaint.Status.PENDING: ComplaintEvent.Type.PENDING,
        Complaint.Status.PUBLISHED: ComplaintEvent.Type.PUBLISHED,
        Complaint.Status.RESOLVED: ComplaintEvent.Type.RESOLVED,
        Complaint.Status.REJECTED: ComplaintEvent.Type.REJECTED,
        Complaint.Status.REMOVED: ComplaintEvent.Type.REMOVED,
    }

    if created:
        record_event(
            instance,
            ComplaintEvent.Type.CREATED,
            source_key=f"complaint:{instance.pk}:created",
            occurred_at=instance.created_at,
        )

        initial_type = status_event_map.get(instance.status)

        if initial_type:
            record_event(
                instance,
                initial_type,
                source_key=f"complaint:{instance.pk}:initial:{instance.status}",
                occurred_at=instance.updated_at,
            )

        return

    previous = getattr(
        instance,
        "_timeline_previous_status",
        None,
    )

    if previous and previous != instance.status:
        event_type = status_event_map.get(instance.status)

        if event_type:
            record_event(
                instance,
                event_type,
                source_key=(
                    f"complaint:{instance.pk}:status:"
                    f"{instance.status}:"
                    f"{instance.updated_at.isoformat()}"
                ),
                occurred_at=instance.updated_at,
            )