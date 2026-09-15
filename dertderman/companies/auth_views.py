from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from accounts.models import User
from accounts.redirects import safe_role_next
from core.rate_limit import (
    clear_rate_limit,
    client_ip,
    consume_rate_limit,
    rate_limit_status,
)

from .forms import (
    CompanyAuthenticationForm,
    CompanyReapplicationForm,
    COMPANY_REGISTRATION_ERROR,
    CompanyRegistrationForm,
)
from .services import (
    active_company_memberships_for,
    resubmit_company_application,
)


AUTH_RATE_LIMIT_MESSAGE = (
    "Çok fazla giriş denemesi yapıldı. Lütfen kısa bir süre sonra tekrar deneyin."
)

REGISTER_RATE_LIMIT_MESSAGE = (
    "Çok fazla şirket kayıt denemesi yapıldı. Lütfen daha sonra tekrar deneyin."
)

LOGIN_IDENTITY_LIMIT = 5
LOGIN_IP_LIMIT = 20
LOGIN_WINDOW_SECONDS = 15 * 60

REGISTER_IP_LIMIT = 10
REGISTER_WINDOW_SECONDS = 60 * 60

REAPPLY_IDENTITY_LIMIT = 5
REAPPLY_IP_LIMIT = 20
REAPPLY_WINDOW_SECONDS = 15 * 60

REAPPLY_RATE_LIMIT_MESSAGE = (
    "Çok fazla yeniden başvuru denemesi yapıldı. "
    "Lütfen kısa bir süre sonra tekrar deneyin."
)


@never_cache
@csrf_protect
@require_http_methods(["GET", "HEAD", "POST"])
def company_register(request):
    if request.user.is_authenticated:
        if (
            request.user.user_type == User.UserType.COMPANY
            and active_company_memberships_for(request.user).exists()
        ):
            return redirect("companies:company_panel")

        raise PermissionDenied

    if request.method == "POST":
        decision = consume_rate_limit(
            scope="company-register-ip",
            identifier=client_ip(request),
            limit=REGISTER_IP_LIMIT,
            window_seconds=REGISTER_WINDOW_SECONDS,
        )

        if not decision.allowed:
            form = CompanyRegistrationForm(request.POST)
            form.add_error(None, REGISTER_RATE_LIMIT_MESSAGE)

            response = render(
                request,
                "companies/company_register.html",
                {"form": form},
                status=429,
            )

            response["Retry-After"] = str(decision.retry_after)
            return response

    form = CompanyRegistrationForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            form.save()

        except IntegrityError:
            # clean_email() yalnızca ön kontroldür.
            # Yarış durumlarında veritabanı constraint'i belirleyicidir.
            form.add_error(
                "email",
                COMPANY_REGISTRATION_ERROR,
            )

        else:
            messages.success(
                request,
                (
                    "Şirket başvurunuz alındı. "
                    "Yönetim onayından sonra kurumsal hesabınız aktif olacaktır."
                ),
                extra_tags="company-application",
            )

            return redirect("company_auth:login")

    return render(
        request,
        "companies/company_register.html",
        {"form": form},
    )


@method_decorator(never_cache, name="dispatch")
@method_decorator(csrf_protect, name="dispatch")
class CompanyLoginView(LoginView):
    template_name = "companies/company_login.html"
    authentication_form = CompanyAuthenticationForm
    http_method_names = [
        "get",
        "head",
        "post",
        "options",
    ]

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if (
                request.user.user_type == User.UserType.COMPANY
                and active_company_memberships_for(
                    request.user
                ).exists()
            ):
                next_url = safe_role_next(
                    request,
                    request.user.user_type,
                )

                return redirect(
                    next_url
                    or "companies:company_panel"
                )

            raise PermissionDenied

        return super().dispatch(
            request,
            *args,
            **kwargs,
        )

    def _rate_identifiers(self):
        ip = client_ip(self.request)

        email = (
            self.request.POST.get(
                "email",
                "",
            )
            or ""
        ).strip().casefold()

        return (
            ip,
            f"{ip}\0{email}",
        )

    def post(self, request, *args, **kwargs):
        ip, identity = self._rate_identifiers()

        identity_status = rate_limit_status(
            scope="company-login-identity",
            identifier=identity,
            limit=LOGIN_IDENTITY_LIMIT,
            window_seconds=LOGIN_WINDOW_SECONDS,
        )

        ip_status = rate_limit_status(
            scope="company-login-ip",
            identifier=ip,
            limit=LOGIN_IP_LIMIT,
            window_seconds=LOGIN_WINDOW_SECONDS,
        )

        if (
            not identity_status.allowed
            or not ip_status.allowed
        ):
            form = self.get_form()

            form.add_error(
                None,
                AUTH_RATE_LIMIT_MESSAGE,
            )

            response = super().form_invalid(form)
            response.status_code = 429
            response["Retry-After"] = str(
                LOGIN_WINDOW_SECONDS
            )

            return response

        return super().post(
            request,
            *args,
            **kwargs,
        )

    def form_invalid(self, form):
        ip, identity = self._rate_identifiers()

        consume_rate_limit(
            scope="company-login-identity",
            identifier=identity,
            limit=LOGIN_IDENTITY_LIMIT,
            window_seconds=LOGIN_WINDOW_SECONDS,
        )

        consume_rate_limit(
            scope="company-login-ip",
            identifier=ip,
            limit=LOGIN_IP_LIMIT,
            window_seconds=LOGIN_WINDOW_SECONDS,
        )

        return super().form_invalid(form)

    def form_valid(self, form):
        _, identity = self._rate_identifiers()

        clear_rate_limit(
            scope="company-login-identity",
            identifier=identity,
        )

        return super().form_valid(form)

    def get_success_url(self):
        return (
            safe_role_next(
                self.request,
                self.request.user.user_type,
            )
            or reverse(
                "companies:company_panel"
            )
        )


@never_cache
@csrf_protect
@require_http_methods(["GET", "HEAD", "POST"])
def company_reapply(request):
    """
    Reddedilmiş şirket başvurusunun
    mevcut hesap bilgileriyle yeniden gönderilmesi.
    """

    if request.user.is_authenticated:
        if (
            request.user.user_type
            == User.UserType.COMPANY
            and active_company_memberships_for(
                request.user
            ).exists()
        ):
            return redirect(
                "companies:company_panel"
            )

        raise PermissionDenied

    if request.method == "POST":
        ip = client_ip(request)

        email = (
            request.POST.get(
                "email",
                "",
            )
            or ""
        ).strip().casefold()

        identity = f"{ip}\0{email}"

        identity_decision = consume_rate_limit(
            scope="company-reapply-identity",
            identifier=identity,
            limit=REAPPLY_IDENTITY_LIMIT,
            window_seconds=REAPPLY_WINDOW_SECONDS,
        )

        ip_decision = consume_rate_limit(
            scope="company-reapply-ip",
            identifier=ip,
            limit=REAPPLY_IP_LIMIT,
            window_seconds=REAPPLY_WINDOW_SECONDS,
        )

        if (
            not identity_decision.allowed
            or not ip_decision.allowed
        ):
            form = CompanyReapplicationForm(
                request.POST,
                request=request,
            )

            form.add_error(
                None,
                REAPPLY_RATE_LIMIT_MESSAGE,
            )

            response = render(
                request,
                "companies/company_reapply.html",
                {
                    "form": form,
                },
                status=429,
            )

            response["Retry-After"] = str(
                max(
                    identity_decision.retry_after,
                    ip_decision.retry_after,
                )
            )

            return response

    form = CompanyReapplicationForm(
        request.POST or None,
        request=request,
    )

    if (
        request.method == "POST"
        and form.is_valid()
    ):
        try:
            resubmit_company_application(
                user=form.user_cache,
                company_id=(
                    form.company_cache.pk
                ),
                company_name=(
                    form.cleaned_data[
                        "company_name"
                    ]
                ),
                category=(
                    form.cleaned_data[
                        "category"
                    ]
                ),
                phone=(
                    form.cleaned_data[
                        "phone"
                    ]
                ),
                website=(
                    form.cleaned_data[
                        "website"
                    ]
                ),
            )

        except ValidationError:
            form.add_error(
                None,
                (
                    "Yeniden başvuru bilgileri "
                    "doğrulanamadı."
                ),
            )

        else:
            ip = client_ip(request)

            email = (
                form.cleaned_data[
                    "email"
                ]
                .strip()
                .casefold()
            )

            clear_rate_limit(
                scope="company-reapply-identity",
                identifier=f"{ip}\0{email}",
            )

            messages.success(
                request,
                (
                    "Şirket başvurunuz yeniden "
                    "incelemeye gönderildi. "
                    "Yönetim onayından sonra "
                    "kurumsal erişiminiz açılacaktır."
                ),
                extra_tags="company-application",
            )

            return redirect(
                "company_auth:login"
            )

    return render(
        request,
        "companies/company_reapply.html",
        {
            "form": form,
        },
    )