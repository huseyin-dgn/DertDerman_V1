from dataclasses import dataclass
from datetime import timedelta

from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
)
from django.db import (
    IntegrityError,
    transaction,
)
from django.utils import timezone

from .models import (
    Complaint,
    DermanPost,
    DermanReaction,
)
from .selectors import (
    public_complaints_for_update,
)
from .services import _locked_actor


DERMAN_CREATE_LIMIT_24_HOURS = 10


class DermanStateConflict(Exception):
    pass


class DermanAlreadyExists(Exception):
    pass


class DermanRateLimited(Exception):
    pass


@dataclass(frozen=True)
class DermanReactionResult:
    action: str
    reaction_type: str = ""


def _locked_published_complaint(
    complaint_id,
):
    """
    Derman işlemleri için parent complaint'i
    transaction içinde tekrar doğrular ve kilitler.

    Yeni Derman / reaction yalnızca hâlâ PUBLISHED
    olan public şikayetlerde yapılabilir.
    """

    try:
        return (
            public_complaints_for_update()
            .get(
                pk=complaint_id,
                status=Complaint.Status.PUBLISHED,
            )
        )

    except Complaint.DoesNotExist as exc:
        raise DermanStateConflict from exc


def _validate_reaction_type(
    reaction_type,
):
    reaction_type = (
        reaction_type or ""
    ).strip().upper()

    if (
        reaction_type
        not in DermanReaction.Type.values
    ):
        raise ValidationError(
            {
                "reaction_type": (
                    "Geçersiz Derman Ol tepkisi."
                ),
            }
        )

    return reaction_type


@transaction.atomic
def create_derman(
    *,
    complaint_id,
    actor,
    body,
):
    """
    Bir USER'ın bir şikayete ömür boyu tek
    Derman Ol paylaşımı oluşturmasını sağlar.

    Başarılı kayıt PENDING durumunda oluşturulur.
    """

    actor = _locked_actor(
        actor,
        allowed_roles={"USER"},
    )

    complaint = (
        _locked_published_complaint(
            complaint_id
        )
    )

    # Kullanıcı kendi şikayetine
    # Derman Ol paylaşımı yapamaz.
    if complaint.user_id == actor.pk:
        raise PermissionDenied

    # Lifetime kuralı:
    # WITHDRAWN / REJECTED / REMOVED dahil herhangi
    # bir eski kayıt varsa yeniden paylaşım yapılamaz.
    if (
        DermanPost.objects
        .filter(
            complaint=complaint,
            author_user=actor,
        )
        .exists()
    ):
        raise DermanAlreadyExists

    # Spam/bot koruması.
    #
    # Actor satırı select_for_update ile kilitli
    # olduğu için aynı kullanıcıdan gelen paralel
    # create istekleri bu kontrolden seri geçer.
    now = timezone.now()

    cutoff = (
        now
        - timedelta(
            hours=24
        )
    )

    recent_count = (
        DermanPost.objects
        .filter(
            author_user=actor,
            created_at__gte=cutoff,
        )
        .count()
    )

    if (
        recent_count
        >= DERMAN_CREATE_LIMIT_24_HOURS
    ):
        raise DermanRateLimited

    derman = DermanPost(
        complaint=complaint,
        author_user=actor,
        body=(body or "").strip(),
        status=DermanPost.Status.PENDING,
    )

    try:
        # Savepoint kullanıyoruz.
        #
        # Böylece DB UNIQUE constraint nedeniyle
        # IntegrityError oluşursa dış transaction
        # kullanılabilir durumda kalır.
        with transaction.atomic():
            derman.save()

    except (
        IntegrityError,
        ValidationError,
    ) as exc:
        # Paralel bir işlem lifetime unique
        # constraint'i kazanmış olabilir.
        if (
            DermanPost.objects
            .filter(
                complaint=complaint,
                author_user=actor,
            )
            .exists()
        ):
            raise DermanAlreadyExists from exc

        # Body validation gibi gerçek validation
        # hatalarını saklama.
        raise

    return derman


@transaction.atomic
def withdraw_derman(
    *,
    derman_id,
    actor,
):
    """
    Kullanıcı kendi Derman paylaşımını geri çeker.

    PENDING veya PUBLISHED -> WITHDRAWN

    Geri çekme yeni paylaşım hakkı doğurmaz;
    DB'deki lifetime unique kayıt korunur.
    """

    actor = _locked_actor(
        actor,
        allowed_roles={"USER"},
    )

    try:
        derman = (
            DermanPost.objects
            .select_for_update()
            .get(
                pk=derman_id,
                author_user=actor,
            )
        )

    except DermanPost.DoesNotExist:
        # Ownership bilgisi sızdırmamak için
        # yetkisiz kayıt erişimi ayrıca
        # açıklanmaz.
        raise PermissionDenied

    # Aynı withdrawal POST'u tekrar gelirse
    # güvenli/idempotent davran.
    if (
        derman.status
        == DermanPost.Status.WITHDRAWN
    ):
        return derman

    if (
        derman.status
        not in (
            DermanPost.Status.PENDING,
            DermanPost.Status.PUBLISHED,
        )
    ):
        raise DermanStateConflict

    withdrawn_at = timezone.now()

    updated = (
        DermanPost.objects
        .filter(
            pk=derman.pk,
            status__in=(
                DermanPost.Status.PENDING,
                DermanPost.Status.PUBLISHED,
            ),
        )
        .update(
            status=DermanPost.Status.WITHDRAWN,
            withdrawn_at=withdrawn_at,
        )
    )

    if updated != 1:
        raise DermanStateConflict

    derman.status = (
        DermanPost.Status.WITHDRAWN
    )

    derman.withdrawn_at = (
        withdrawn_at
    )

    return derman


@transaction.atomic
def toggle_derman_reaction(
    *,
    derman_id,
    actor,
    reaction_type,
):
    """
    LIKE / DISLIKE toggle işlemi.

    Yok + LIKE       -> LIKE oluştur
    LIKE + LIKE      -> kaldır
    LIKE + DISLIKE   -> DISLIKE
    DISLIKE + LIKE   -> LIKE
    DISLIKE + DISLIKE-> kaldır
    """

    actor = _locked_actor(
        actor,
        allowed_roles={"USER"},
    )

    reaction_type = (
        _validate_reaction_type(
            reaction_type
        )
    )

    # Önce yalnızca parent complaint id'sini
    # öğreniyoruz. Asıl güvenlik kontrolleri
    # aşağıdaki kilitli sorgularda tekrar yapılır.
    try:
        derman_reference = (
            DermanPost.objects
            .only(
                "pk",
                "complaint_id",
            )
            .get(
                pk=derman_id
            )
        )

    except DermanPost.DoesNotExist as exc:
        raise DermanStateConflict from exc

    complaint = (
        _locked_published_complaint(
            derman_reference.complaint_id
        )
    )

    try:
        derman = (
            DermanPost.objects
            .select_for_update()
            .get(
                pk=derman_id,
                complaint=complaint,
            )
        )

    except DermanPost.DoesNotExist as exc:
        raise DermanStateConflict from exc

    # Pending/rejected/withdrawn/removed
    # Derman üzerinde reaction yapılamaz.
    if (
        derman.status
        != DermanPost.Status.PUBLISHED
    ):
        raise DermanStateConflict

    # Kendi Derman paylaşımına
    # LIKE/DISLIKE yasak.
    if (
        derman.author_user_id
        == actor.pk
    ):
        raise PermissionDenied

    current = (
        DermanReaction.objects
        .select_for_update()
        .filter(
            derman=derman,
            user=actor,
        )
        .first()
    )

    if current is not None:
        # Aynı butona tekrar basılırsa
        # tepki kaldırılır.
        if (
            current.reaction_type
            == reaction_type
        ):
            current.delete()

            return DermanReactionResult(
                action="REMOVED",
                reaction_type="",
            )

        # LIKE <-> DISLIKE geçişi.
        current.reaction_type = (
            reaction_type
        )

        current.save(
            update_fields=(
                "reaction_type",
                "updated_at",
            )
        )

        return DermanReactionResult(
            action="UPDATED",
            reaction_type=reaction_type,
        )

    try:
        with transaction.atomic():
            DermanReaction.objects.create(
                derman=derman,
                user=actor,
                reaction_type=reaction_type,
            )

    except IntegrityError:
        # DB unique constraint son savunma hattı.
        #
        # Normal uygulama akışında actor lock
        # nedeniyle buraya düşülmemesi gerekir.
        current = (
            DermanReaction.objects
            .select_for_update()
            .filter(
                derman=derman,
                user=actor,
            )
            .first()
        )

        if current is None:
            raise

        if (
            current.reaction_type
            == reaction_type
        ):
            current.delete()

            return DermanReactionResult(
                action="REMOVED",
                reaction_type="",
            )

        current.reaction_type = (
            reaction_type
        )

        current.save(
            update_fields=(
                "reaction_type",
                "updated_at",
            )
        )

        return DermanReactionResult(
            action="UPDATED",
            reaction_type=reaction_type,
        )

    return DermanReactionResult(
        action="CREATED",
        reaction_type=reaction_type,
    )