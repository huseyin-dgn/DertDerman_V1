from django.contrib.auth import login, logout
from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.views.generic.edit import FormView

from core.decorators import role_required

from .forms import ProfileUpdateForm, RegisterForm, UserAuthenticationForm
from .models import User
from .badges import primary_badge, resolve_user_badges
from .redirects import safe_role_next


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
    authentication_form = UserAuthenticationForm
    redirect_authenticated_user = True

    def get_success_url(self):
        return safe_role_next(self.request, self.request.user.user_type) or role_redirect_url(self.request.user)


@role_required(User.UserType.USER)
def profile(request):
    badges = resolve_user_badges(request.user)
    return render(request, "accounts/profile.html", {
        "user_badges": badges,
        "primary_user_badge": primary_badge(badges),
    })


@role_required(User.UserType.USER)
def profile_edit(request):
    if request.method == "POST":
        form = ProfileUpdateForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profil bilgileriniz güncellendi.")
            return redirect("accounts:profile")
    else:
        form = ProfileUpdateForm(instance=request.user)

    return render(request, "accounts/profile_edit.html", {"form": form})


@method_decorator(role_required(User.UserType.USER), name="dispatch")
class SecurePasswordChangeView(PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Şifreniz başarıyla güncellendi.")
        return response


@method_decorator(never_cache, name="dispatch")
class SecureLogoutView(LogoutView):
    next_page = reverse_lazy("core:home")

    def get_success_url(self):
        return reverse("core:home")


@never_cache
@require_POST
def invalidate_history_session(request):
    if not request.user.is_authenticated:
        return HttpResponse(status=401)
    logout(request)
    return HttpResponse(status=204)

@never_cache
def account_entry(request):
    if request.user.is_authenticated:
        return redirect(role_redirect_url(request.user))
    return redirect("accounts:login")
