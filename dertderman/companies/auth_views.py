from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from accounts.models import User

from .forms import CompanyAuthenticationForm, CompanyRegistrationForm
from .services import active_company_memberships_for


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

    form = CompanyRegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(
            request,
            "Şirket başvurunuz alındı. Yönetim onayından sonra kurumsal hesabınız aktif olacaktır.",
        )
        return redirect("company_auth:login")
    return render(request, "companies/company_register.html", {"form": form})


@method_decorator(never_cache, name="dispatch")
@method_decorator(csrf_protect, name="dispatch")
class CompanyLoginView(LoginView):
    template_name = "companies/company_login.html"
    authentication_form = CompanyAuthenticationForm
    http_method_names = ["get", "head", "post", "options"]

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if (
                request.user.user_type == User.UserType.COMPANY
                and active_company_memberships_for(request.user).exists()
            ):
                return redirect("companies:company_panel")
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("companies:company_panel")
