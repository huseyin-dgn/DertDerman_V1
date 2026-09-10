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


LOGIN_ERROR = "Yönetim paneli giriş bilgileri doğrulanamadı."


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

    def get_success_url(self):
        return safe_role_next(self.request, self.request.user.user_type) or reverse("adminx:home")
