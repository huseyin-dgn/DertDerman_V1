from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .anti_abuse import consume_complaint_edit_rate_limit
from .events import record_event
from .models import Complaint, ComplaintEvent


class ComplaintStateConflict(Exception):
    pass


class ComplaintEditRateLimited(Exception):
    def __init__(self, retry_after):
        self.retry_after = max(1, int(retry_after))
        super().__init__("Complaint edit rate limit exceeded.")


def _locked_actor(actor, *, allowed_roles):
    if (
        not getattr(actor, "is_authenticated", False)
        or not getattr(actor, "pk", None)
        or getattr(actor, "user_type", None) not in allowed_roles
    ):
        raise PermissionDenied

    locked = actor.__class__.objects.select_for_update().get(pk=actor.pk)
    if (
        locked.user_type not in allowed_roles
        or not locked.is_active
        or locked.is_permanently_closed
        or (
            locked.user_type == "USER"
            and not locked.can_perform_user_mutations
        )
    ):
        raise PermissionDenied
    return locked


@transaction.atomic
def edit_complaint(*, complaint, form, actor):
    actor = _locked_actor(actor, allowed_roles={"USER"})
    locked = Complaint.objects.select_for_update().get(
        pk=complaint.pk,
        user=actor,
    )

    # The form is validated before this lock is acquired. If moderation or
    # another lifecycle action committed in that window, this stale edit must
    # not overwrite the newer decision. A complaint that was already public
    # when the request loaded remains intentionally editable and is re-pended.
    if (
        locked.status != complaint.status
        or locked.updated_at != complaint.updated_at
        or locked.withdrawn_at != complaint.withdrawn_at
        or locked.removed_for_violation != complaint.removed_for_violation
        or locked.violation_removed_at != complaint.violation_removed_at
    ):
        raise ComplaintStateConflict

    if (
        locked.withdrawn_at
        or locked.status in (
            Complaint.Status.RESOLVED,
            Complaint.Status.REMOVED,
        )
        or locked.removed_for_violation
        or locked.violation_removed_at is not None
    ):
        raise ComplaintStateConflict

    rate_limit = consume_complaint_edit_rate_limit(
        user=actor,
        complaint_id=locked.pk,
    )

    if not rate_limit.allowed:
        raise ComplaintEditRateLimited(
            rate_limit.retry_after
        )

    selected_company = form.cleaned_data["company"]
    if selected_company.pk != locked.company_id:
        from companies.models import Company

        selected_company = (
            Company.objects.select_for_update()
            .filter(
                pk=selected_company.pk,
                is_active=True,
                approval_status=Company.ApprovalStatus.APPROVED,
                archived_at__isnull=True,
            )
            .first()
        )
        if selected_company is None:
            raise ComplaintStateConflict

    for field in ("company", "category", "title", "description"):
        setattr(
            locked,
            field,
            selected_company if field == "company" else form.cleaned_data[field],
        )

    if locked.status in (
        Complaint.Status.PUBLISHED,
        Complaint.Status.REJECTED,
    ):
        locked.status = Complaint.Status.PENDING

    locked.save(
        update_fields=(
            "company",
            "category",
            "title",
            "description",
            "status",
            "updated_at",
        )
    )
    edited = locked

    occurred_at = timezone.now()

    event_key = (
        f"complaint:{edited.pk}:edited:"
        f"{uuid4().hex}"
    )

    record_event(
        edited,
        ComplaintEvent.Type.EDITED,
        actor_type=ComplaintEvent.Actor.USER,
        message=(
            "Şikayet kullanıcı tarafından düzenlendi "
            "ve yeniden incelemeye gönderildi."
        ),
        source_key=event_key,
        occurred_at=occurred_at,
    )

    from notifications.services import send_admins

    send_admins(
        kind="MODERATION",
        event_key=event_key,
        title=(
            "Düzenlenen şikayet yeniden "
            "moderasyon bekliyor."
        ),
        message=edited.title,
        complaint=edited,
        company=edited.company,
    )

    return edited


@transaction.atomic
def withdraw_complaint(*, complaint, actor):
    actor = _locked_actor(actor, allowed_roles={"USER"})
    locked = Complaint.objects.select_for_update().get(
        pk=complaint.pk,
        user=actor,
    )

    if locked.withdrawn_at:
        return locked

    if (
        locked.status not in (
            Complaint.Status.PENDING,
            Complaint.Status.PUBLISHED,
        )
        or locked.removed_for_violation
        or locked.violation_removed_at is not None
    ):
        raise ComplaintStateConflict

    occurred_at = timezone.now()

    locked.withdrawn_at = occurred_at
    locked.save(
        update_fields=(
            "withdrawn_at",
            "updated_at",
        )
    )

    event_key = (
        f"complaint:{locked.pk}:withdrawn"
    )

    record_event(
        locked,
        ComplaintEvent.Type.WITHDRAWN,
        actor_type=ComplaintEvent.Actor.USER,
        message=(
            "Şikayet kullanıcı tarafından "
            "geri çekildi."
        ),
        source_key=event_key,
        occurred_at=occurred_at,
    )

    from companies.models import (
        CompanyNotification,
    )
    from companies.panel_events import (
        record_complaint_notification,
    )

    record_complaint_notification(
        locked,
        CompanyNotification.Kind.UPDATED,
        event_key=event_key,
        notify_user=False,
    )

    return locked


@transaction.atomic
def resolve_complaint(
    *,
    complaint_id,
    actor,
    owner_id=None,
):
    actor = _locked_actor(actor, allowed_roles={"USER", "ADMIN"})

    queryset = (
        Complaint.objects
        .select_for_update(of=("self",))
        .select_related(
            "company",
            "user",
        )
    )

    if actor.user_type == "USER":
        if owner_id is not None and owner_id != actor.pk:
            raise PermissionDenied
        queryset = queryset.filter(user=actor)
    elif owner_id is not None:
        queryset = queryset.filter(
            user_id=owner_id
        )

    complaint = queryset.get(
        pk=complaint_id
    )

    if (
        complaint.status
        != Complaint.Status.PUBLISHED
        or complaint.withdrawn_at
        or complaint.removed_for_violation
        or complaint.violation_removed_at is not None
    ):
        raise ComplaintStateConflict

    occurred_at = timezone.now()

    updated = Complaint.objects.filter(
        pk=complaint.pk,
        status=Complaint.Status.PUBLISHED,
        withdrawn_at__isnull=True,
        removed_for_violation=False,
        violation_removed_at__isnull=True,
    ).update(
        status=Complaint.Status.RESOLVED,
        updated_at=occurred_at,
    )

    if updated != 1:
        raise ComplaintStateConflict

    complaint.status = Complaint.Status.RESOLVED
    complaint.updated_at = occurred_at

    actor_type = (
        ComplaintEvent.Actor.USER
        if actor.user_type == "USER"
        else ComplaintEvent.Actor.ADMIN
    )

    message = (
        "Kullanıcı sorunun çözüldüğünü onayladı."
        if actor_type == ComplaintEvent.Actor.USER
        else (
            "Yönetici tarafından çözüldü "
            "olarak işaretlendi."
        )
    )

    event_key = (
        f"complaint:{complaint.pk}:resolved:"
        f"{actor_type.lower()}"
    )

    record_event(
        complaint,
        ComplaintEvent.Type.RESOLVED,
        actor_type=actor_type,
        message=message,
        source_key=event_key,
        occurred_at=occurred_at,
    )

    from companies.models import (
        CompanyNotification,
    )
    from companies.panel_events import (
        record_complaint_notification,
    )

    record_complaint_notification(
        complaint,
        CompanyNotification.Kind.RESOLVED,
        event_key=event_key,
        notify_user=(
            actor_type
            == ComplaintEvent.Actor.ADMIN
        ),
    )

    return complaint
