from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic.edit import FormView

from .forms import ProfileUpdateForm, RegisterForm
from .models import User


def role_redirect_url(user):
    if user.user_type == User.UserType.USER:
        return reverse("dashboard:home")
    if user.user_type == User.UserType.COMPANY:
        return reverse("companies:company_panel")
    if user.user_type == User.UserType.ADMIN:
        return reverse("adminx:home")
    return reverse("core:home")


@method_decorator(never_cache, name="dispatch")
class RegisterView(FormView):
    template_name = "accounts/register.html"
    form_class = RegisterForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(role_redirect_url(request.user))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        return redirect("dashboard:home")


@method_decorator(never_cache, name="dispatch")
class SecureLoginView(LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        return role_redirect_url(self.request.user)


@never_cache
@login_required
def profile(request):
    return render(request, "accounts/profile.html")


@never_cache
@login_required
def profile_edit(request):
    if request.method == "POST":
        form = ProfileUpdateForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            return redirect("accounts:profile")
    else:
        form = ProfileUpdateForm(instance=request.user)

    return render(request, "accounts/profile_edit.html", {"form": form})


@method_decorator(never_cache, name="dispatch")
class SecurePasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")


@method_decorator(never_cache, name="dispatch")
class SecureLogoutView(LogoutView):
    next_page = reverse_lazy("core:home")


@never_cache
def account_entry(request):
    if request.user.is_authenticated:
        return redirect(role_redirect_url(request.user))
    return redirect("accounts:login")
