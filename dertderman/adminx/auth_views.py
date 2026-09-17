from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect

from accounts.models import User
from accounts.redirects import safe_role_next
from core.rate_limit import (
    AuthRateLimitPolicy,
    clear_auth_identity,
    client_ip,
    auth_rate_limit_status,
    consume_auth_failure,
)


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

        return super().form_valid(form)

    def get_success_url(self):
        return safe_role_next(self.request, self.request.user.user_type) or reverse("adminx:home")
