from django.contrib import messages
from django.core.exceptions import (
    ValidationError,
)
from django.shortcuts import redirect
from django.views.decorators.http import (
    require_POST,
)

from accounts.models import User
from core.decorators import role_required

from .derman_company_services import (
    DermanCompanyResponseAlreadyExists,
    DermanCompanyResponseNotFound,
    DermanCompanyResponseProRequired,
    DermanCompanyResponseStateConflict,
    create_derman_company_response,
    update_derman_company_response,
)
from .forms import (
    DermanCompanyResponseForm,
)


def _public_complaints_redirect():
    return redirect(
        "complaints:public_list"
    )


def _response_detail_redirect(
    response,
):
    return redirect(
        "complaints:public_detail",
        pk=response.derman.complaint_id,
    )


def _first_form_error(
    form,
):
    errors = (
        form.errors
        .get_json_data()
    )

    for field_errors in (
        errors.values()
    ):
        if field_errors:
            return (
                field_errors[0]
                .get(
                    "message",
                    (
                        "Şirket yanıtı "
                        "kaydedilemedi."
                    ),
                )
            )

    return (
        "Şirket yanıtı kaydedilemedi. "
        "Lütfen formu kontrol edin."
    )


@role_required(
    User.UserType.COMPANY
)
@require_POST
def derman_company_response_create(
    request,
    derman_pk,
):
    form = (
        DermanCompanyResponseForm(
            request.POST
        )
    )

    if not form.is_valid():
        messages.error(
            request,
            _first_form_error(
                form
            ),
        )

        return (
            _public_complaints_redirect()
        )

    try:
        response = (
            create_derman_company_response(
                derman_id=derman_pk,
                actor=request.user,
                body=(
                    form.cleaned_data[
                        "body"
                    ]
                ),
            )
        )

    except (
        DermanCompanyResponseAlreadyExists
    ):
        messages.info(
            request,
            (
                "Şirketiniz bu Derman için "
                "daha önce resmi yanıt "
                "paylaşmış."
            ),
        )

        return (
            _public_complaints_redirect()
        )

    except (
        DermanCompanyResponseProRequired
    ):
        messages.warning(
            request,
            (
                "Dermanlara resmi şirket "
                "yanıtı verebilmek için "
                "aktif DertDerman Pro "
                "paketi gerekir."
            ),
        )

        return (
            _public_complaints_redirect()
        )

    except (
        DermanCompanyResponseStateConflict
    ):
        messages.warning(
            request,
            (
                "Bu Derman artık şirket "
                "yanıtına açık değil."
            ),
        )

        return (
            _public_complaints_redirect()
        )

    except ValidationError as error:
        message = (
            error.messages[0]
            if error.messages
            else (
                "Şirket yanıtı "
                "kaydedilemedi."
            )
        )

        messages.error(
            request,
            message,
        )

        return (
            _public_complaints_redirect()
        )

    messages.success(
        request,
        (
            "Resmi şirket yanıtı "
            "yayınlandı."
        ),
    )

    return (
        _response_detail_redirect(
            response
        )
    )


@role_required(
    User.UserType.COMPANY
)
@require_POST
def derman_company_response_update(
    request,
    derman_pk,
):
    form = (
        DermanCompanyResponseForm(
            request.POST
        )
    )

    if not form.is_valid():
        messages.error(
            request,
            _first_form_error(
                form
            ),
        )

        return (
            _public_complaints_redirect()
        )

    try:
        response = (
            update_derman_company_response(
                derman_id=derman_pk,
                actor=request.user,
                body=(
                    form.cleaned_data[
                        "body"
                    ]
                ),
            )
        )

    except (
        DermanCompanyResponseNotFound
    ):
        messages.warning(
            request,
            (
                "Güncellenecek resmi "
                "şirket yanıtı bulunamadı."
            ),
        )

        return (
            _public_complaints_redirect()
        )

    except (
        DermanCompanyResponseProRequired
    ):
        messages.warning(
            request,
            (
                "Resmi Derman yanıtını "
                "güncellemek için aktif "
                "DertDerman Pro paketi gerekir."
            ),
        )

        return (
            _public_complaints_redirect()
        )

    except (
        DermanCompanyResponseStateConflict
    ):
        messages.warning(
            request,
            (
                "Bu Derman yanıtı artık "
                "güncellenemez."
            ),
        )

        return (
            _public_complaints_redirect()
        )

    except ValidationError as error:
        message = (
            error.messages[0]
            if error.messages
            else (
                "Şirket yanıtı "
                "güncellenemedi."
            )
        )

        messages.error(
            request,
            message,
        )

        return (
            _public_complaints_redirect()
        )

    messages.success(
        request,
        (
            "Resmi şirket yanıtı "
            "güncellendi."
        ),
    )

    return (
        _response_detail_redirect(
            response
        )
    )