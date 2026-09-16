from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
)
from django.db import (
    IntegrityError,
    transaction,
)

from companies.models import (
    Company,
)
from companies.panel_permissions import (
    PROFILE_ROLES,
)
from companies.plans import (
    active_pro_subscriptions,
)
from companies.services import (
    active_company_memberships_for,
)

from .models import (
    Complaint,
    DermanCompanyResponse,
    DermanPost,
)
from .selectors import (
    public_complaints_for_update,
)
from .services import (
    _locked_actor,
)


class DermanCompanyResponseStateConflict(
    Exception
):
    pass


class DermanCompanyResponseAlreadyExists(
    Exception
):
    pass


class DermanCompanyResponseNotFound(
    Exception
):
    pass


class DermanCompanyResponseProRequired(
    Exception
):
    pass


def _clean_company_response_body(
    body,
):
    body = (
        body or ""
    ).strip()

    if len(body) < 20:
        raise ValidationError(
            {
                "body": (
                    "Şirket yanıtı en az "
                    "20 karakter olmalıdır."
                ),
            }
        )

    if len(body) > 3000:
        raise ValidationError(
            {
                "body": (
                    "Şirket yanıtı en fazla "
                    "3000 karakter olabilir."
                ),
            }
        )

    return body


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
            DermanCompanyResponseStateConflict
        ) from exc


def _locked_response_context(
    *,
    derman_id,
    actor,
):
    """
    Şirket Derman cevabı için gerekli bütün
    authorization ve lifecycle kontrollerini
    transaction içinde yeniden yapar.

    Lock sırası:
    actor
    -> complaint
    -> company
    -> Derman
    -> membership
    -> Pro subscription
    """

    actor = _locked_actor(
        actor,
        allowed_roles={"COMPANY"},
    )

    derman_reference = (
        _derman_reference(
            derman_id
        )
    )

    try:
        complaint = (
            public_complaints_for_update()
            .get(
                pk=(
                    derman_reference
                    .complaint_id
                ),
                status=(
                    Complaint.Status.PUBLISHED
                ),
            )
        )

    except Complaint.DoesNotExist as exc:
        raise (
            DermanCompanyResponseStateConflict
        ) from exc

    company = (
        Company.objects
        .select_for_update()
        .filter(
            pk=complaint.company_id,
            is_active=True,
            is_verified=True,
            approval_status=(
                Company
                .ApprovalStatus
                .APPROVED
            ),
            archived_at__isnull=True,
        )
        .first()
    )

    if company is None:
        raise (
            DermanCompanyResponseStateConflict
        )

    try:
        derman = (
            DermanPost.objects
            .select_for_update()
            .get(
                pk=derman_id,
                complaint_id=complaint.pk,
                status=(
                    DermanPost.Status.PUBLISHED
                ),
            )
        )

    except DermanPost.DoesNotExist as exc:
        raise (
            DermanCompanyResponseStateConflict
        ) from exc

    membership = (
        active_company_memberships_for(
            actor
        )
        .select_for_update(
            of=("self",)
        )
        .filter(
            company_id=company.pk,
            role__in=PROFILE_ROLES,
        )
        .first()
    )

    if membership is None:
        raise PermissionDenied

    has_active_pro = (
        active_pro_subscriptions()
        .select_for_update(
            of=("self",)
        )
        .filter(
            company_id=company.pk,
        )
        .exists()
    )

    if not has_active_pro:
        raise (
            DermanCompanyResponseProRequired
        )

    return (
        actor,
        complaint,
        company,
        derman,
        membership,
    )


@transaction.atomic
def create_derman_company_response(
    *,
    derman_id,
    actor,
    body,
):
    body = (
        _clean_company_response_body(
            body
        )
    )

    (
        actor,
        complaint,
        company,
        derman,
        membership,
    ) = _locked_response_context(
        derman_id=derman_id,
        actor=actor,
    )

    existing = (
        DermanCompanyResponse.objects
        .select_for_update()
        .filter(
            derman_id=derman.pk,
            company_id=company.pk,
        )
        .exists()
    )

    if existing:
        raise (
            DermanCompanyResponseAlreadyExists
        )

    response = (
        DermanCompanyResponse(
            derman=derman,
            company=company,
            author_user=actor,
            body=body,
        )
    )

    try:
        with transaction.atomic():
            response.save()

    except (
        IntegrityError,
        ValidationError,
    ) as exc:
        duplicate_exists = (
            DermanCompanyResponse.objects
            .filter(
                derman_id=derman.pk,
                company_id=company.pk,
            )
            .exists()
        )

        if duplicate_exists:
            raise (
                DermanCompanyResponseAlreadyExists
            ) from exc

        raise

    return response


@transaction.atomic
def update_derman_company_response(
    *,
    derman_id,
    actor,
    body,
):
    body = (
        _clean_company_response_body(
            body
        )
    )

    (
        actor,
        complaint,
        company,
        derman,
        membership,
    ) = _locked_response_context(
        derman_id=derman_id,
        actor=actor,
    )

    try:
        response = (
            DermanCompanyResponse.objects
            .select_for_update()
            .get(
                derman_id=derman.pk,
                company_id=company.pk,
            )
        )

    except (
        DermanCompanyResponse.DoesNotExist
    ) as exc:
        raise (
            DermanCompanyResponseNotFound
        ) from exc

    if response.body == body:
        return response

    response.body = body

    response.save(
        update_fields=(
            "body",
            "updated_at",
        )
    )

    return response