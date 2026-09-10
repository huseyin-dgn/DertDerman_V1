from django.db import transaction
from django.utils import timezone
from uuid import uuid4

from .events import record_event
from .models import Complaint, ComplaintEvent


class ComplaintStateConflict(Exception):
    pass


@transaction.atomic
def edit_complaint(*, complaint, form, actor):
    locked = Complaint.objects.select_for_update().get(pk=complaint.pk, user=actor)
    if locked.withdrawn_at or locked.status == Complaint.Status.RESOLVED:
        raise ComplaintStateConflict
    edited = form.save(commit=False)
    edited.pk = locked.pk
    edited.user = locked.user
    if locked.status in (Complaint.Status.PUBLISHED, Complaint.Status.REJECTED):
        edited.status = Complaint.Status.PENDING
    else:
        edited.status = locked.status
    edited.save()
    occurred_at = timezone.now()
    event_key = f"complaint:{edited.pk}:edited:{uuid4().hex}"
    record_event(
        edited,
        ComplaintEvent.Type.EDITED,
        actor_type=ComplaintEvent.Actor.USER,
        message="Şikayet kullanıcı tarafından düzenlendi ve yeniden incelemeye gönderildi.",
        source_key=event_key,
        occurred_at=occurred_at,
    )
    from notifications.services import send_admins

    send_admins(
        kind="MODERATION",
        event_key=event_key,
        title="Düzenlenen şikayet yeniden moderasyon bekliyor.",
        message=edited.title,
        complaint=edited,
        company=edited.company,
    )
    return edited


@transaction.atomic
def withdraw_complaint(*, complaint, actor):
    locked = Complaint.objects.select_for_update().get(pk=complaint.pk, user=actor)
    if locked.withdrawn_at:
        return locked
    occurred_at = timezone.now()
    locked.withdrawn_at = occurred_at
    locked.save(update_fields=("withdrawn_at", "updated_at"))
    event_key = f"complaint:{locked.pk}:withdrawn"
    record_event(
        locked,
        ComplaintEvent.Type.WITHDRAWN,
        actor_type=ComplaintEvent.Actor.USER,
        message="Şikayet kullanıcı tarafından geri çekildi.",
        source_key=event_key,
        occurred_at=occurred_at,
    )
    from companies.models import CompanyNotification
    from companies.panel_events import record_complaint_notification

    record_complaint_notification(
        locked, CompanyNotification.Kind.UPDATED, event_key=event_key, notify_user=False
    )
    return locked


@transaction.atomic
def resolve_complaint(*, complaint_id, actor, owner_id=None):
    queryset = Complaint.objects.select_for_update().select_related("company", "user")
    if owner_id is not None:
        queryset = queryset.filter(user_id=owner_id)
    complaint = queryset.get(pk=complaint_id)
    if complaint.status != Complaint.Status.PUBLISHED:
        raise ComplaintStateConflict

    occurred_at = timezone.now()
    Complaint.objects.filter(pk=complaint.pk, status=Complaint.Status.PUBLISHED).update(
        status=Complaint.Status.RESOLVED, updated_at=occurred_at
    )
    complaint.status = Complaint.Status.RESOLVED
    complaint.updated_at = occurred_at
    actor_type = ComplaintEvent.Actor.USER if actor.user_type == "USER" else ComplaintEvent.Actor.ADMIN
    message = (
        "Kullanıcı sorunun çözüldüğünü onayladı."
        if actor_type == ComplaintEvent.Actor.USER
        else "Yönetici tarafından çözüldü olarak işaretlendi."
    )
    event_key = f"complaint:{complaint.pk}:resolved:{actor_type.lower()}"
    record_event(
        complaint,
        ComplaintEvent.Type.RESOLVED,
        actor_type=actor_type,
        message=message,
        source_key=event_key,
        occurred_at=occurred_at,
    )

    from companies.models import CompanyNotification
    from companies.panel_events import record_complaint_notification

    record_complaint_notification(
        complaint,
        CompanyNotification.Kind.RESOLVED,
        event_key=event_key,
        notify_user=actor_type == ComplaintEvent.Actor.ADMIN,
    )
    return complaint
