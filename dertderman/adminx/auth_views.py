from urllib.parse import urlsplit

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from accounts.models import User
from accounts.redirects import safe_role_next
from core.rate_limit import (
    AuthRateLimitPolicy,
    clear_auth_identity,
    client_ip,
    auth_rate_limit_status,
    consume_auth_failure,
)
from core.session_security import (
    mark_reauthenticated,
)

from .decorators import admin_required


LOGIN_ERROR = "Yönetim paneli giriş bilgileri doğrulanamadı."
AUTH_RATE_LIMIT_MESSAGE = (
    "Çok fazla giriş denemesi yapıldı. "
    "Lütfen kısa bir süre sonra tekrar deneyin."
)

ADMIN_LOGIN_POLICY = AuthRateLimitPolicy(
    pair_limit=4,
    pair_window_seconds=15 * 60,
    identity_limit=8,
    identity_window_seconds=60 * 60,
    ip_limit=15,
    ip_window_seconds=15 * 60,
)

ADMIN_REAUTH_POLICY = AuthRateLimitPolicy(
    pair_limit=5,
    pair_window_seconds=15 * 60,
    identity_limit=10,
    identity_window_seconds=60 * 60,
    ip_limit=20,
    ip_window_seconds=15 * 60,
)

REAUTH_ERROR = "Mevcut şifre doğrulanamadı."
REAUTH_RATE_LIMIT_MESSAGE = (
    "Çok fazla yeniden doğrulama denemesi yapıldı. "
    "Lütfen kısa bir süre sonra tekrar deneyin."
)


class AdminAuthenticationForm(AuthenticationForm):
    error_messages = {"invalid_login": LOGIN_ERROR, "inactive": LOGIN_ERROR}

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.user_type != User.UserType.ADMIN:
            raise ValidationError(LOGIN_ERROR, code="invalid_login")


@method_decorator(never_cache, name="dispatch")
@method_decorator(csrf_protect, name="dispatch")
class AdminLoginView(LoginView):
    template_name = "adminx/login.html"
    authentication_form = AdminAuthenticationForm
    http_method_names = ["get", "head", "post", "options"]

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if request.user.user_type != User.UserType.ADMIN:
                raise PermissionDenied
            return redirect("adminx:home")
        return super().dispatch(request, *args, **kwargs)

    def _rate_identifiers(self):
        ip = client_ip(self.request)

        username = (
            self.request.POST.get(
                "username",
                "",
            )
            or ""
        ).strip().casefold()

        return ip, username

    def post(
        self,
        request,
        *args,
        **kwargs,
    ):
        ip, identity = self._rate_identifiers()

        decision = auth_rate_limit_status(
            scope="admin-login",
            ip_address=ip,
            identity=identity,
            policy=ADMIN_LOGIN_POLICY,
        )

        if not decision.allowed:
            # Never perform credential verification after the
            # management login has already been throttled.
            form = self.get_form_class()(
                request=request,
            )

            response = self.render_to_response(
                self.get_context_data(
                    form=form,
                    auth_rate_limit_message=(
                        AUTH_RATE_LIMIT_MESSAGE
                    ),
                ),
                status=429,
            )

            response["Retry-After"] = str(
                decision.retry_after
            )

            return response

        return super().post(
            request,
            *args,
            **kwargs,
        )

    def form_invalid(self, form):
        ip, identity = self._rate_identifiers()

        decision = consume_auth_failure(
            scope="admin-login",
            ip_address=ip,
            identity=identity,
            policy=ADMIN_LOGIN_POLICY,
        )

        # Eşzamanlı isteklerde birkaç request pre-check'i aynı
        # anda geçmiş olabilir. Atomic cache increment sonucunda
        # limit aşılırsa bu request de 429 ile kapatılır.
        if not decision.allowed:
            response = self.render_to_response(
                self.get_context_data(
                    form=form,
                    auth_rate_limit_message=(
                        AUTH_RATE_LIMIT_MESSAGE
                    ),
                ),
                status=429,
            )

            response["Retry-After"] = str(
                decision.retry_after
            )

            return response

        return super().form_invalid(form)

    def form_valid(self, form):
        ip, identity = self._rate_identifiers()

        clear_auth_identity(
            scope="admin-login",
            ip_address=ip,
            identity=identity,
        )

        response = super().form_valid(
            form
        )

        # Basarili yonetici girisi ayni zamanda
        # step-up authentication icin taze parola
        # dogrulamasi sayilir.
        mark_reauthenticated(
            self.request.session
        )

        return response

    def get_success_url(self):
        return safe_role_next(self.request, self.request.user.user_type) or reverse("adminx:home")

class AdminReauthenticationForm(forms.Form):
    password = forms.CharField(
        label="Mevcut şifre",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete":
                    "current-password",
            }
        ),
    )


def _safe_admin_reauth_next(request):
    candidate = (
        request.POST.get("next")
        or request.GET.get("next")
        or ""
    ).strip()

    home_url = reverse(
        "adminx:home"
    )

    if not candidate:
        return home_url

    if not url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={
            request.get_host()
        },
        require_https=request.is_secure(),
    ):
        return home_url

    path = urlsplit(
        candidate
    ).path

    if not path.startswith(
        home_url
    ):
        return home_url

    if path in {
        reverse("adminx:login"),
        reverse("adminx:reauth"),
    }:
        return home_url

    return candidate


@admin_required
@never_cache
@csrf_protect
@require_http_methods(
    ["GET", "HEAD", "POST"]
)
def admin_reauthenticate(request):
    next_url = (
        _safe_admin_reauth_next(
            request
        )
    )

    form = AdminReauthenticationForm(
        request.POST
        if request.method == "POST"
        else None
    )

    context = {
        "form": form,
        "next": next_url,
    }

    if request.method != "POST":
        return render(
            request,
            "adminx/reauth.html",
            context,
        )

    ip = client_ip(request)
    identity = str(
        request.user.pk
    )

    decision = auth_rate_limit_status(
        scope="admin-reauth",
        ip_address=ip,
        identity=identity,
        policy=ADMIN_REAUTH_POLICY,
    )

    if not decision.allowed:
        context[
            "auth_rate_limit_message"
        ] = REAUTH_RATE_LIMIT_MESSAGE

        response = render(
            request,
            "adminx/reauth.html",
            context,
            status=429,
        )

        response["Retry-After"] = str(
            decision.retry_after
        )

        return response

    if not form.is_valid():
        return render(
            request,
            "adminx/reauth.html",
            context,
        )

    current_admin = (
        User.objects
        .filter(
            pk=request.user.pk,
            user_type=(
                User.UserType.ADMIN
            ),
            is_active=True,
            is_permanently_closed=False,
        )
        .first()
    )

    if current_admin is None:
        raise PermissionDenied

    if not current_admin.check_password(
        form.cleaned_data["password"]
    ):
        form.add_error(
            "password",
            REAUTH_ERROR,
        )

        decision = consume_auth_failure(
            scope="admin-reauth",
            ip_address=ip,
            identity=identity,
            policy=ADMIN_REAUTH_POLICY,
        )

        if not decision.allowed:
            context[
                "auth_rate_limit_message"
            ] = (
                REAUTH_RATE_LIMIT_MESSAGE
            )

            response = render(
                request,
                "adminx/reauth.html",
                context,
                status=429,
            )

            response[
                "Retry-After"
            ] = str(
                decision.retry_after
            )

            return response

        return render(
            request,
            "adminx/reauth.html",
            context,
        )

    clear_auth_identity(
        scope="admin-reauth",
        ip_address=ip,
        identity=identity,
    )

    # Step-up authentication sonrasi session key
    # rotate edilir. Eski/calinmis cookie ayni session'i
    # kullanmaya devam edemez.
    request.session.cycle_key()

    mark_reauthenticated(
        request.session
    )

    return redirect(
        next_url
    )
