from django.contrib import messages
from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
)
from django.db import (
    IntegrityError,
    transaction,
)
from django.http import Http404
from django.shortcuts import (
    get_object_or_404,
    redirect,
)
from django.views.decorators.http import (
    require_POST,
)

from accounts.models import User
from core.decorators import role_required

from .derman_services import (
    DermanAlreadyExists,
    DermanRateLimited,
    DermanStateConflict,
    create_derman,
    toggle_derman_reaction,
    withdraw_derman,
)
from .forms import (
    ContentReportForm,
    DermanCreateForm,
)
from .models import (
    ContentReport,
    DermanPost,
)
from .reporting_policy import (
    check_general_reporting_allowed,
)
from .selectors import (
    public_complaints_for_update,
)


def _public_detail_redirect(
    complaint_id,
):
    return redirect(
        "complaints:public_detail",
        pk=complaint_id,
    )


def _ensure_derman_belongs_to_complaint(
    *,
    complaint_id,
    derman_id,
):
    exists = (
        DermanPost.objects
        .filter(
            pk=derman_id,
            complaint_id=complaint_id,
        )
        .exists()
    )

    if not exists:
        raise Http404


def _locked_derman_reporter(
    request,
):
    actor = (
        User.objects
        .select_for_update()
        .get(
            pk=request.user.pk
        )
    )

    if (
        actor.user_type
        != User.UserType.USER
        or not actor.can_perform_user_mutations
    ):
        raise PermissionDenied

    return actor


@role_required(
    User.UserType.USER
)
@require_POST
def derman_create(
    request,
    pk,
):
    form = DermanCreateForm(
        request.POST
    )

    if not form.is_valid():
        first_error = (
            next(
                iter(
                    form.errors
                    .get_json_data()
                    .values()
                ),
                None,
            )
        )

        if first_error:
            message = (
                first_error[0]
                .get(
                    "message",
                    "Derman gönderilemedi.",
                )
            )
        else:
            message = (
                "Derman gönderilemedi. "
                "Lütfen formu kontrol edin."
            )

        messages.error(
            request,
            message,
        )

        return _public_detail_redirect(
            pk
        )

    try:
        create_derman(
            complaint_id=pk,
            actor=request.user,
            body=form.cleaned_data[
                "body"
            ],
        )

    except DermanAlreadyExists:
        messages.info(
            request,
            (
                "Bu şikayet için daha önce "
                "Derman Ol paylaşımı yaptınız. "
                "Her şikayet için yalnızca "
                "bir Derman paylaşabilirsiniz."
            ),
        )

    except DermanRateLimited:
        messages.error(
            request,
            (
                "Son 24 saat içinde çok fazla "
                "Derman Ol paylaşımı yaptınız. "
                "Lütfen daha sonra tekrar deneyin."
            ),
        )

    except DermanStateConflict:
        messages.warning(
            request,
            (
                "Bu şikayet artık Derman Ol "
                "paylaşımına açık değil."
            ),
        )

    except ValidationError as error:
        message = (
            error.messages[0]
            if error.messages
            else (
                "Derman gönderilemedi. "
                "Lütfen içeriği kontrol edin."
            )
        )

        messages.error(
            request,
            message,
        )

    else:
        messages.success(
            request,
            (
                "Dermanınız incelemeye gönderildi. "
                "Yönetim onayından sonra "
                "yayınlanacaktır."
            ),
        )

    return _public_detail_redirect(
        pk
    )


@role_required(
    User.UserType.USER
)
@require_POST
def derman_withdraw(
    request,
    pk,
    derman_pk,
):
    _ensure_derman_belongs_to_complaint(
        complaint_id=pk,
        derman_id=derman_pk,
    )

    try:
        withdraw_derman(
            derman_id=derman_pk,
            actor=request.user,
        )

    except DermanStateConflict:
        messages.warning(
            request,
            (
                "Bu Derman artık geri "
                "çekilemez."
            ),
        )

    else:
        messages.success(
            request,
            "Derman paylaşımınız geri çekildi.",
        )

    return _public_detail_redirect(
        pk
    )


@role_required(
    User.UserType.USER
)
@require_POST
def derman_react(
    request,
    pk,
    derman_pk,
):
    _ensure_derman_belongs_to_complaint(
        complaint_id=pk,
        derman_id=derman_pk,
    )

    try:
        result = (
            toggle_derman_reaction(
                derman_id=derman_pk,
                actor=request.user,
                reaction_type=(
                    request.POST.get(
                        "reaction_type",
                        "",
                    )
                ),
            )
        )

    except DermanStateConflict:
        messages.warning(
            request,
            (
                "Bu Derman paylaşımına "
                "artık tepki verilemez."
            ),
        )

    except ValidationError:
        messages.error(
            request,
            "Geçersiz tepki türü.",
        )

    else:
        if result.action == "REMOVED":
            messages.success(
                request,
                "Tepkiniz kaldırıldı.",
            )

        elif result.action == "UPDATED":
            messages.success(
                request,
                "Tepkiniz güncellendi.",
            )

        else:
            messages.success(
                request,
                "Tepkiniz kaydedildi.",
            )

    return _public_detail_redirect(
        pk
    )


@role_required(
    User.UserType.USER
)
@require_POST
@transaction.atomic
def derman_report(
    request,
    pk,
    derman_pk,
):
    actor = _locked_derman_reporter(
        request
    )

    reporting_policy = (
        check_general_reporting_allowed(
            user=actor,
            request=request,
        )
    )

    if not reporting_policy.allowed:
        messages.error(
            request,
            reporting_policy.message,
        )

        return _public_detail_redirect(
            pk
        )

    complaint = get_object_or_404(
        public_complaints_for_update(),
        pk=pk,
    )

    derman = get_object_or_404(
        DermanPost.objects
        .select_for_update()
        .select_related(
            "author_user",
        ),
        pk=derman_pk,
        complaint=complaint,
        status=DermanPost.Status.PUBLISHED,
    )

    if (
        derman.author_user_id
        == actor.pk
    ):
        messages.warning(
            request,
            (
                "Kendi Derman paylaşımınızı "
                "raporlayamazsınız."
            ),
        )

        return _public_detail_redirect(
            complaint.pk
        )

    if (
        ContentReport.objects
        .filter(
            reporter=actor,
            derman=derman,
        )
        .exists()
    ):
        messages.info(
            request,
            (
                "Bu Derman paylaşımını "
                "daha önce raporladınız."
            ),
        )

        return _public_detail_redirect(
            complaint.pk
        )

    form = ContentReportForm(
        request.POST
    )

    if not form.is_valid():
        messages.error(
            request,
            (
                "Rapor gönderilemedi. "
                "Lütfen geçerli bir "
                "neden seçin."
            ),
        )

        return _public_detail_redirect(
            complaint.pk
        )

    report = form.save(
        commit=False
    )

    report.reporter = actor

    report.target_type = (
        ContentReport
        .TargetType
        .DERMAN
    )

    report.complaint = None
    report.comment = None
    report.derman = derman

    report.status = (
        ContentReport
        .Status
        .PENDING
    )

    try:
        report.save()

    except (
        ValidationError,
        IntegrityError,
    ):
        messages.info(
            request,
            (
                "Bu Derman paylaşımını "
                "daha önce raporladınız."
            ),
        )

        return _public_detail_redirect(
            complaint.pk
        )

    from notifications.services import (
        notify_admins_content_report,
    )

    notify_admins_content_report(
        report
    )

    messages.success(
        request,
        (
            "Raporunuz alındı. "
            "Derman paylaşımı yönetim ekibi "
            "tarafından incelenecek."
        ),
    )

    return _public_detail_redirect(
        complaint.pk
    )