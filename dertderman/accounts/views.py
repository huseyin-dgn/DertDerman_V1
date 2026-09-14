import logging

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordChangeView,
)
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_http_methods
from django.views.generic.edit import FormView

from core.decorators import role_required
from core.rate_limit import (
    clear_rate_limit,
    client_ip,
    consume_rate_limit,
    rate_limit_status,
)
from .badges import (
    primary_badge,
    resolve_user_badges,
)
from .email_verification import (
    enqueue_email_verification,
    resolve_email_verification_token,
    verify_email_verification_token,
)
from .forms import (
    ProfileUpdateForm,
    RegisterForm,
    UserAuthenticationForm,
)
from .models import User
from .redirects import safe_role_next


logger = logging.getLogger(__name__)

AUTH_RATE_LIMIT_MESSAGE = (
    "Çok fazla giriş denemesi yapıldı. Lütfen kısa bir süre sonra tekrar deneyin."
)
REGISTER_RATE_LIMIT_MESSAGE = (
    "Çok fazla kayıt denemesi yapıldı. Lütfen daha sonra tekrar deneyin."
)
LOGIN_IDENTITY_LIMIT = 5
LOGIN_IP_LIMIT = 20
LOGIN_WINDOW_SECONDS = 15 * 60
REGISTER_IP_LIMIT = 10
REGISTER_WINDOW_SECONDS = 60 * 60


def role_redirect_url(user):
    if user.user_type == User.UserType.USER:
        return reverse("dashboard:home")

    if user.user_type == User.UserType.COMPANY:
        return reverse(
            "companies:company_panel"
        )

    if user.user_type == User.UserType.ADMIN:
        return reverse("adminx:home")

    return reverse("core:home")


@method_decorator(
    never_cache,
    name="dispatch",
)
class RegisterView(FormView):
    template_name = "accounts/register.html"
    form_class = RegisterForm

    def dispatch(
        self,
        request,
        *args,
        **kwargs,
    ):
        if request.user.is_authenticated:
            return redirect(
                role_redirect_url(
                    request.user
                )
            )

        return super().dispatch(
            request,
            *args,
            **kwargs,
        )

    def post(self, request, *args, **kwargs):
        decision = consume_rate_limit(
            scope="user-register-ip",
            identifier=client_ip(request),
            limit=REGISTER_IP_LIMIT,
            window_seconds=REGISTER_WINDOW_SECONDS,
        )
        if not decision.allowed:
            form = self.get_form()
            form.add_error(None, REGISTER_RATE_LIMIT_MESSAGE)
            response = self.render_to_response(
                self.get_context_data(form=form),
                status=429,
            )
            response["Retry-After"] = str(decision.retry_after)
            return response
        return super().post(request, *args, **kwargs)

    def form_valid(
        self,
        form,
    ):
        # RegisterForm persists is_verified=False. The user is deliberately
        # NOT logged in here; verification must complete first.
        try:
            with transaction.atomic():
                user = form.save()
                enqueue_email_verification(user)
        except Exception as exc:
            logger.error(
                "Registration verification enqueue failed: exception_type=%s",
                exc.__class__.__name__,
            )
            form.add_error(
                None,
                "Kayıt şu anda tamamlanamadı. Lütfen tekrar deneyin.",
            )
            return self.form_invalid(form)

        messages.success(
            self.request,
            (
                "Hesabınız oluşturuldu. Doğrulama bağlantısını "
                "e-posta adresinize gönderdik."
            ),
        )

        return redirect(
            "accounts:email_verification_pending"
        )


@never_cache
def email_verification_pending(request):
    if request.user.is_authenticated:
        return redirect(role_redirect_url(request.user))

    return render(
        request,
        "accounts/email_verification_pending.html",
    )


@never_cache
@require_http_methods(["GET", "POST"])
def email_verification_confirm(request, token):
    if request.method == "GET":
        token_valid = (
            resolve_email_verification_token(token)
            is not None
        )

        return render(
            request,
            "accounts/email_verification_confirm.html",
            {"token_valid": token_valid},
            status=200 if token_valid else 400,
        )

    user = verify_email_verification_token(token)

    if user is None:
        return render(
            request,
            "accounts/email_verification_confirm.html",
            {"token_valid": False},
            status=400,
        )

    messages.success(
        request,
        "E-posta adresiniz doğrulandı. Artık giriş yapabilirsiniz.",
    )

    return redirect("accounts:login")


@method_decorator(
    never_cache,
    name="dispatch",
)
class SecureLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = UserAuthenticationForm
    redirect_authenticated_user = True

    def _rate_identifiers(self):
        ip = client_ip(self.request)
        username = (self.request.POST.get("username", "") or "").strip().casefold()
        return ip, f"{ip}\0{username}"

    def post(self, request, *args, **kwargs):
        ip, identity = self._rate_identifiers()
        identity_status = rate_limit_status(
            scope="user-login-identity",
            identifier=identity,
            limit=LOGIN_IDENTITY_LIMIT,
            window_seconds=LOGIN_WINDOW_SECONDS,
        )
        ip_status = rate_limit_status(
            scope="user-login-ip",
            identifier=ip,
            limit=LOGIN_IP_LIMIT,
            window_seconds=LOGIN_WINDOW_SECONDS,
        )
        if not identity_status.allowed or not ip_status.allowed:
            form = self.get_form()
            form.add_error(None, AUTH_RATE_LIMIT_MESSAGE)
            response = super().form_invalid(form)
            response.status_code = 429
            response["Retry-After"] = str(LOGIN_WINDOW_SECONDS)
            return response
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        ip, identity = self._rate_identifiers()
        consume_rate_limit(
            scope="user-login-identity",
            identifier=identity,
            limit=LOGIN_IDENTITY_LIMIT,
            window_seconds=LOGIN_WINDOW_SECONDS,
        )
        consume_rate_limit(
            scope="user-login-ip",
            identifier=ip,
            limit=LOGIN_IP_LIMIT,
            window_seconds=LOGIN_WINDOW_SECONDS,
        )
        return super().form_invalid(form)

    def form_valid(self, form):
        _, identity = self._rate_identifiers()
        clear_rate_limit(scope="user-login-identity", identifier=identity)
        return super().form_valid(form)

    def get_success_url(self):
        return (
            safe_role_next(
                self.request,
                self.request.user.user_type,
            )
            or role_redirect_url(
                self.request.user
            )
        )


def public_profile(
    request,
    username,
):
    account = get_object_or_404(
        User.objects.only(
            "pk",
            "username",
            "first_name",
            "last_name",
            "date_joined",
            "user_type",
            "selected_avatar",
            "profile_image",
            "is_active",
        ),
        username=username,
        user_type=(
            User.UserType.USER
        ),
        is_active=True,
    )

    badges = resolve_user_badges(
        account
    )

    from complaints.forms import (
        UserReportForm,
    )

    from complaints.models import (
        Complaint,
        ComplaintComment,
        ComplaintReaction,
        UserReport,
    )

    from complaints.selectors import (
        public_complaints,
    )

    # Sadece gerçekten herkese açık
    # şikayetleri kullanıcı profilinde göster.
    public_complaint_qs = (
        public_complaints()
        .filter(
            user=account
        )
    )

    complaint_count = (
        public_complaint_qs.count()
    )

    resolved_count = (
        public_complaint_qs
        .filter(
            status=(
                Complaint.Status.RESOLVED
            )
        )
        .count()
    )

    # Kullanıcının yalnızca public
    # şikayetler altındaki aktif yorumları.
    comment_count = (
        ComplaintComment.objects
        .filter(
            author_user=account,
            is_active=True,

            complaint__status__in=(
                Complaint.Status.PUBLISHED,
                Complaint.Status.RESOLVED,
            ),

            complaint__withdrawn_at__isnull=True,

            complaint__removed_for_violation=False,

            complaint__company__is_active=True,
        )
        .count()
    )

    # Kullanıcının public şikayetlerine
    # gelen toplam tepki.
    received_reaction_count = (
        ComplaintReaction.objects
        .filter(
            complaint__user=account,

            complaint__status__in=(
                Complaint.Status.PUBLISHED,
                Complaint.Status.RESOLVED,
            ),

            complaint__withdrawn_at__isnull=True,

            complaint__removed_for_violation=False,

            complaint__company__is_active=True,
        )
        .count()
    )

    # Public profilde en fazla
    # 6 şikayet / sayfa.
    complaint_page = Paginator(
        public_complaint_qs,
        6,
    ).get_page(
        request.GET.get(
            "complaint_page"
        )
    )

    viewer_is_user = (
        request.user.is_authenticated
        and request.user.user_type
        == User.UserType.USER
    )

    is_self = (
        viewer_is_user
        and request.user.pk
        == account.pk
    )

    viewer_is_suspended = (
        viewer_is_user
        and getattr(
            request.user,
            "is_currently_suspended",
            False,
        )
    )

    already_reported = False

    if (
        viewer_is_user
        and not is_self
    ):
        already_reported = (
            UserReport.objects
            .filter(
                reporter=request.user,
                reported_user=account,
            )
            .exists()
        )

    can_report = (
        viewer_is_user
        and not is_self
        and not viewer_is_suspended
        and not already_reported
    )

    return render(
        request,
        "accounts/public_profile.html",
        {
            "account": account,

            "user_badges": badges,

            "primary_user_badge":
                primary_badge(
                    badges
                ),

            "complaint_count":
                complaint_count,

            "resolved_count":
                resolved_count,

            "comment_count":
                comment_count,

            "received_reaction_count":
                received_reaction_count,

            "complaint_page":
                complaint_page,

            "viewer_is_user":
                viewer_is_user,

            "is_self":
                is_self,

            "viewer_is_suspended":
                viewer_is_suspended,

            "can_report":
                can_report,

            "already_reported":
                already_reported,

            "user_report_form":
                UserReportForm(),
        },
    )


@role_required(
    User.UserType.USER
)
def profile(request):
    badges = resolve_user_badges(
        request.user
    )

    return render(
        request,
        "accounts/profile.html",
        {
            "user_badges":
                badges,

            "primary_user_badge":
                primary_badge(
                    badges
                ),
        },
    )


@role_required(
    User.UserType.USER
)
def profile_edit(request):
    if request.method == "POST":
        form = ProfileUpdateForm(
            request.POST,
            instance=request.user,
        )

        if form.is_valid():
            form.save()

            messages.success(
                request,
                (
                    "Profil bilgileriniz "
                    "güncellendi."
                ),
            )

            return redirect(
                "accounts:profile"
            )

    else:
        form = ProfileUpdateForm(
            instance=request.user
        )

    return render(
        request,
        "accounts/profile_edit.html",
        {
            "form": form,
        },
    )


@method_decorator(
    role_required(
        User.UserType.USER
    ),
    name="dispatch",
)
class SecurePasswordChangeView(
    PasswordChangeView
):
    template_name = (
        "accounts/password_change.html"
    )

    success_url = reverse_lazy(
        "accounts:profile"
    )

    def form_valid(
        self,
        form,
    ):
        response = super().form_valid(
            form
        )

        messages.success(
            self.request,
            (
                "Şifreniz başarıyla "
                "güncellendi."
            ),
        )

        return response


@method_decorator(
    never_cache,
    name="dispatch",
)
class SecureLogoutView(
    LogoutView
):
    next_page = reverse_lazy(
        "core:home"
    )

    def get_success_url(self):
        return reverse(
            "core:home"
        )


@never_cache
@require_POST
def invalidate_history_session(
    request
):
    if not request.user.is_authenticated:
        return HttpResponse(
            status=401
        )

    logout(request)

    return HttpResponse(
        status=204
    )


@never_cache
def account_entry(request):
    if request.user.is_authenticated:
        return redirect(
            role_redirect_url(
                request.user
            )
        )

    return redirect(
        "accounts:login"
    )
