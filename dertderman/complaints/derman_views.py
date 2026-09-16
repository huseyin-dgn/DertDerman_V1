from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

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
from .forms import DermanCreateForm
from .models import (
    DermanPost,
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