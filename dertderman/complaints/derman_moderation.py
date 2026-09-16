from django.core.exceptions import (
    PermissionDenied,
)
from django.db import transaction
from django.utils import timezone

from adminx.services import (
    lock_current_admin,
)
from companies.models import (
    CompanyNotification,
)
from companies.plans import (
    company_has_active_pro,
)

from .models import (
    Complaint,
    DermanPost,
)
from .selectors import (
    public_complaint_filter,
)


class DermanModerationStateConflict(
    Exception
):
    pass


def _derman_reference(
    derman_id,
):
    try:
        return (
            DermanPost.objects
            .only(
                "pk",
                "complaint_id",
            )
            .get(
                pk=derman_id,
            )
        )

    except DermanPost.DoesNotExist as exc:
        raise (
            DermanModerationStateConflict
        ) from exc


def _locked_moderation_context(
    *,
    derman_id,
    actor,
):
    """
    Lock sırası:

    ADMIN actor
    -> parent Complaint
    -> Derman

    Böylece diğer Derman servislerindeki
    parent -> Derman sırasıyla uyumlu kalır.
    """

    actor = lock_current_admin(
        actor
    )

    reference = _derman_reference(
        derman_id
    )

    try:
        complaint = (
            Complaint.objects
            .select_for_update()
            .select_related(
                "company",
                "user",
            )
            .get(
                pk=reference.complaint_id,
            )
        )

    except Complaint.DoesNotExist as exc:
        raise (
            DermanModerationStateConflict
        ) from exc

    try:
        derman = (
            DermanPost.objects
            .select_for_update()
            .select_related(
                "author_user",
            )
            .get(
                pk=derman_id,
                complaint_id=complaint.pk,
            )
        )

    except DermanPost.DoesNotExist as exc:
        raise (
            DermanModerationStateConflict
        ) from exc

    return (
        actor,
        complaint,
        derman,
    )


def _complaint_allows_derman_publish(
    complaint,
):
    if (
        complaint.status
        != Complaint.Status.PUBLISHED
    ):
        return False

    return (
        Complaint.objects
        .filter(
            pk=complaint.pk,
        )
        .filter(
            public_complaint_filter()
        )
        .exists()
    )


def _company_derman_notification(
    *,
    complaint,
    derman,
):
    """
    Derman body hiçbir koşulda
    CompanyNotification içine yazılmaz.

    Böylece şirket daha sonra Pro hakkını
    kaybetse bile geçmiş notification üzerinden
    Derman içeriği sızmaz.
    """

    if company_has_active_pro(
        complaint.company
    ):
        message = (
            "Şikayetinize yayınlanmış yeni "
            "bir Derman eklendi. Dermanı "
            "şikayet detayından "
            "inceleyebilirsiniz."
        )

    else:
        message = (
            "Şikayetinize yayınlanmış yeni "
            "bir Derman eklendi. Derman "
            "içeriğini görmek ve resmi yanıt "
            "vermek için DertDerman Pro'yu "
            "inceleyebilirsiniz."
        )

    notification, _ = (
        CompanyNotification.objects
        .get_or_create(
            event_key=(
                f"derman:{derman.pk}:"
                "published:company"
            ),
            defaults={
                "company_id":
                    complaint.company_id,

                "complaint":
                    complaint,

                "kind":
                    CompanyNotification
                    .Kind
                    .DERMAN,

                "title":
                    "Yeni bir Derman yayınlandı.",

                "message":
                    message,
            },
        )
    )

    return notification


@transaction.atomic
def publish_derman(
    *,
    derman_id,
    actor,
    moderation_note="",
):
    (
        actor,
        complaint,
        derman,
    ) = _locked_moderation_context(
        derman_id=derman_id,
        actor=actor,
    )

    if (
        derman.status
        != DermanPost.Status.PENDING
    ):
        raise (
            DermanModerationStateConflict
        )

    if not (
        _complaint_allows_derman_publish(
            complaint
        )
    ):
        raise (
            DermanModerationStateConflict
        )

    moderation_note = (
        moderation_note or ""
    ).strip()

    now = timezone.now()

    derman.status = (
        DermanPost.Status.PUBLISHED
    )

    derman.published_at = now
    derman.reviewed_at = now
    derman.reviewed_by = actor
    derman.moderation_note = (
        moderation_note
    )

    derman.save(
        update_fields=(
            "status",
            "published_at",
            "reviewed_at",
            "reviewed_by",
            "moderation_note",
        )
    )

    notification = (
        _company_derman_notification(
            complaint=complaint,
            derman=derman,
        )
    )

    from notifications.services import (
        notify_derman_published,
    )

    notify_derman_published(derman)

    return (
        derman,
        notification,
    )


@transaction.atomic
def reject_derman(
    *,
    derman_id,
    actor,
    moderation_note="",
):
    (
        actor,
        complaint,
        derman,
    ) = _locked_moderation_context(
        derman_id=derman_id,
        actor=actor,
    )

    if (
        derman.status
        != DermanPost.Status.PENDING
    ):
        raise (
            DermanModerationStateConflict
        )

    moderation_note = (
        moderation_note or ""
    ).strip()

    now = timezone.now()

    derman.status = (
        DermanPost.Status.REJECTED
    )

    derman.reviewed_at = now
    derman.reviewed_by = actor
    derman.moderation_note = (
        moderation_note
    )

    derman.save(
        update_fields=(
            "status",
            "reviewed_at",
            "reviewed_by",
            "moderation_note",
        )
    )

    from notifications.services import (
        notify_derman_rejected,
    )

    notify_derman_rejected(derman)

    return derman
