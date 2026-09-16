from django.contrib import messages
from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
)
from django.db.models import (
    Count,
    OuterRef,
    Q,
    Subquery,
)
from django.shortcuts import (
    redirect,
    render,
)
from django.views.decorators.http import (
    require_POST,
    require_safe,
)

from complaints.derman_company_services import (
    DermanCompanyResponseAlreadyExists,
    DermanCompanyResponseNotFound,
    DermanCompanyResponseProRequired,
    DermanCompanyResponseStateConflict,
    create_derman_company_response,
    update_derman_company_response,
)
from complaints.forms import (
    DermanCompanyResponseForm,
)
from complaints.models import (
    Complaint,
    DermanCompanyResponse,
    DermanPost,
    DermanReaction,
)
from core.pagination import paginate

from .panel_permissions import (
    PROFILE_ROLES,
    company_panel_required,
)
from .panel_views import panel_context
from .plans import company_has_active_pro


def _company_published_dermans(
    company
):
    response_query = (
        DermanCompanyResponse.objects
        .filter(
            derman_id=OuterRef(
                "pk"
            ),
            company_id=company.pk,
        )
    )

    return (
        DermanPost.objects
        .filter(
            complaint__company=company,
            status=(
                DermanPost
                .Status
                .PUBLISHED
            ),
            complaint__status__in=(
                Complaint.Status.PUBLISHED,
                Complaint.Status.RESOLVED,
            ),
            complaint__withdrawn_at__isnull=True,
            complaint__removed_for_violation=False,
            complaint__violation_removed_at__isnull=True,
        )
        .select_related(
            "complaint",
            "author_user",
        )
        .annotate(
            like_count=Count(
                "reactions",
                filter=Q(
                    reactions__reaction_type=(
                        DermanReaction
                        .Type
                        .LIKE
                    )
                ),
                distinct=True,
            ),

            dislike_count=Count(
                "reactions",
                filter=Q(
                    reactions__reaction_type=(
                        DermanReaction
                        .Type
                        .DISLIKE
                    )
                ),
                distinct=True,
            ),

            company_response_id=Subquery(
                response_query
                .values(
                    "id"
                )[:1]
            ),

            company_response_body=Subquery(
                response_query
                .values(
                    "body"
                )[:1]
            ),

            company_response_created_at=Subquery(
                response_query
                .values(
                    "created_at"
                )[:1]
            ),
        )
        .order_by(
            "-published_at",
            "-pk",
        )
    )


@company_panel_required
@require_safe
def dermans(request):
    is_pro = company_has_active_pro(
        request.company
    )

    can_respond = (
        request.company_membership.role
        in PROFILE_ROLES
    )

    published_count = (
        DermanPost.objects
        .filter(
            complaint__company=(
                request.company
            ),
            status=(
                DermanPost
                .Status
                .PUBLISHED
            ),
            complaint__status__in=(
                Complaint.Status.PUBLISHED,
                Complaint.Status.RESOLVED,
            ),
            complaint__withdrawn_at__isnull=True,
            complaint__removed_for_violation=False,
            complaint__violation_removed_at__isnull=True,
        )
        .count()
    )

    if not is_pro:
        return render(
            request,
            "companies/panel/dermans.html",
            panel_context(
                request,
                "dermans",
                is_pro=False,
                published_count=(
                    published_count
                ),
                can_respond=False,
                page_obj=None,
                metrics=None,
            ),
        )

    queryset = (
        _company_published_dermans(
            request.company
        )
    )

    metrics = {
        "total":
            queryset.count(),

        "answered":
            queryset
            .exclude(
                company_response_id=None
            )
            .count(),

        "waiting":
            queryset
            .filter(
                company_response_id=None
            )
            .count(),
    }

    page_obj = paginate(
        request,
        queryset,
        "company_dermans",
    )

    return render(
        request,
        "companies/panel/dermans.html",
        panel_context(
            request,
            "dermans",
            is_pro=True,
            published_count=(
                published_count
            ),
            can_respond=(
                can_respond
            ),
            page_obj=page_obj,
            metrics=metrics,
            response_form=(
                DermanCompanyResponseForm()
            ),
        ),
    )


def _response_error_message(
    error,
):
    if isinstance(
        error,
        DermanCompanyResponseProRequired,
    ):
        return (
            "Bu işlem için aktif "
            "DertDerman Pro paketi gerekiyor."
        )

    if isinstance(
        error,
        DermanCompanyResponseAlreadyExists,
    ):
        return (
            "Bu Derman için daha önce "
            "resmi yanıt oluşturulmuş."
        )

    if isinstance(
        error,
        DermanCompanyResponseNotFound,
    ):
        return (
            "Düzenlenecek resmi yanıt bulunamadı."
        )

    return (
        "Bu Derman artık resmi şirket "
        "yanıtı işlemine uygun değil."
    )


@company_panel_required
@require_POST
def derman_response_create(
    request,
    pk,
):
    if (
        request.company_membership.role
        not in PROFILE_ROLES
    ):
        raise PermissionDenied

    form = DermanCompanyResponseForm(
        request.POST
    )

    if not form.is_valid():
        messages.error(
            request,
            (
                "Resmi yanıt kaydedilemedi. "
                "Metni kontrol edin."
            ),
        )

        return redirect(
            "companies:dermans"
        )

    try:
        create_derman_company_response(
            derman_id=pk,
            actor=request.user,
            body=form.cleaned_data[
                "body"
            ],
        )

    except (
        DermanCompanyResponseProRequired,
        DermanCompanyResponseAlreadyExists,
        DermanCompanyResponseStateConflict,
    ) as error:
        messages.error(
            request,
            _response_error_message(
                error
            ),
        )

    except ValidationError as error:
        messages.error(
            request,
            (
                error.messages[0]
                if error.messages
                else "Yanıt kaydedilemedi."
            ),
        )

    else:
        messages.success(
            request,
            "Resmi Derman yanıtı yayınlandı.",
        )

    return redirect(
        "companies:dermans"
    )


@company_panel_required
@require_POST
def derman_response_update(
    request,
    pk,
):
    if (
        request.company_membership.role
        not in PROFILE_ROLES
    ):
        raise PermissionDenied

    form = DermanCompanyResponseForm(
        request.POST
    )

    if not form.is_valid():
        messages.error(
            request,
            (
                "Resmi yanıt güncellenemedi. "
                "Metni kontrol edin."
            ),
        )

        return redirect(
            "companies:dermans"
        )

    try:
        update_derman_company_response(
            derman_id=pk,
            actor=request.user,
            body=form.cleaned_data[
                "body"
            ],
        )

    except (
        DermanCompanyResponseProRequired,
        DermanCompanyResponseNotFound,
        DermanCompanyResponseStateConflict,
    ) as error:
        messages.error(
            request,
            _response_error_message(
                error
            ),
        )

    except ValidationError as error:
        messages.error(
            request,
            (
                error.messages[0]
                if error.messages
                else "Yanıt güncellenemedi."
            ),
        )

    else:
        messages.success(
            request,
            "Resmi Derman yanıtı güncellendi.",
        )

    return redirect(
        "companies:dermans"
    )