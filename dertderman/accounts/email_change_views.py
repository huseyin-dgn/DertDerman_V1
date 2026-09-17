import logging

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from django.views.generic import FormView, TemplateView

from core.decorators import no_referrer, role_required
from core.rate_limit import (
    clear_rate_limit,
    consume_rate_limit,
    rate_limit_status,
)
from notifications.email_service import EmailServiceError

from .email_change import (
    apply_email_change_token,
    normalize_email,
    resolve_email_change_token,
    send_email_change_verification,
)
from .models import User


logger = logging.getLogger(__name__)

EMAIL_CHANGE_REQUEST_LIMIT = 3
EMAIL_CHANGE_REQUEST_WINDOW_SECONDS = 60 * 60
EMAIL_CHANGE_PASSWORD_ATTEMPT_LIMIT = 5
EMAIL_CHANGE_PASSWORD_ATTEMPT_WINDOW_SECONDS = 15 * 60
EMAIL_CHANGE_RATE_LIMIT_MESSAGE = (
    "Kısa süre içinde çok fazla e-posta değişikliği istediniz. Lütfen daha sonra tekrar deneyin."
)
EMAIL_CHANGE_PASSWORD_RATE_LIMIT_MESSAGE = (
    "Çok fazla mevcut şifre denemesi yapıldı. "
    "Lütfen kısa bir süre sonra tekrar deneyin."
)


class EmailChangeRequestForm(forms.Form):
    current_password = forms.CharField(
        label="Mevcut şifre",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "current-password",
            }
        ),
    )
    new_email = forms.EmailField(
        label="Yeni e-posta adresi",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
            }
        ),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        cleaned_data = super().clean()
        current_password = cleaned_data.get("current_password")
        new_email = cleaned_data.get("new_email")

        if not current_password or not self.user.check_password(current_password):
            self.add_error(
                "current_password",
                "Mevcut şifreniz doğru değil.",
            )
            return cleaned_data

        if not new_email:
            return cleaned_data

        try:
            normalized = normalize_email(new_email)
        except ValueError:
            self.add_error(
                "new_email",
                "Geçerli bir e-posta adresi girin.",
            )
            return cleaned_data

        if normalized.casefold() == (self.user.email or "").strip().casefold():
            self.add_error(
                "new_email",
                "Yeni e-posta adresi mevcut adresinizden farklı olmalıdır.",
            )
            return cleaned_data

        if (
            User.objects
            .filter(email__iexact=normalized)
            .exclude(pk=self.user.pk)
            .exists()
        ):
            self.add_error(
                "new_email",
                "Bu e-posta adresi başka bir hesapta kullanılıyor.",
            )
            return cleaned_data

        cleaned_data["new_email"] = normalized
        return cleaned_data


@method_decorator(
    role_required(User.UserType.USER),
    name="dispatch",
)
class EmailChangeRequestView(FormView):
    template_name = "accounts/email_change_request.html"
    form_class = EmailChangeRequestForm
    success_url = reverse_lazy("accounts:email_change_pending")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def _password_attempt_identifier(self):
        return self.request.user.pk

    def post(self, request, *args, **kwargs):
        status = rate_limit_status(
            scope="email-change-current-password",
            identifier=self._password_attempt_identifier(),
            limit=EMAIL_CHANGE_PASSWORD_ATTEMPT_LIMIT,
            window_seconds=EMAIL_CHANGE_PASSWORD_ATTEMPT_WINDOW_SECONDS,
        )
        if not status.allowed:
            form = self.get_form()
            form.add_error(None, EMAIL_CHANGE_PASSWORD_RATE_LIMIT_MESSAGE)
            response = super().form_invalid(form)
            response.status_code = 429
            response["Retry-After"] = str(
                EMAIL_CHANGE_PASSWORD_ATTEMPT_WINDOW_SECONDS
            )
            return response
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        if "current_password" in form.errors:
            consume_rate_limit(
                scope="email-change-current-password",
                identifier=self._password_attempt_identifier(),
                limit=EMAIL_CHANGE_PASSWORD_ATTEMPT_LIMIT,
                window_seconds=EMAIL_CHANGE_PASSWORD_ATTEMPT_WINDOW_SECONDS,
            )
        return super().form_invalid(form)

    def form_valid(self, form):
        clear_rate_limit(
            scope="email-change-current-password",
            identifier=self._password_attempt_identifier(),
        )

        decision = consume_rate_limit(
            scope="email-change-user",
            identifier=self.request.user.pk,
            limit=EMAIL_CHANGE_REQUEST_LIMIT,
            window_seconds=EMAIL_CHANGE_REQUEST_WINDOW_SECONDS,
        )
        if not decision.allowed:
            form.add_error(None, EMAIL_CHANGE_RATE_LIMIT_MESSAGE)
            response = self.form_invalid(form)
            response.status_code = 429
            response["Retry-After"] = str(decision.retry_after)
            return response

        try:
            result = send_email_change_verification(
                self.request.user,
                form.cleaned_data["new_email"],
            )
        except (EmailServiceError, ValueError) as exc:
            logger.warning(
                "Email change verification delivery failed: "
                "user_id=%s exception_type=%s",
                self.request.user.pk,
                exc.__class__.__name__,
            )
            form.add_error(
                None,
                "Doğrulama e-postası şu anda gönderilemedi. "
                "Lütfen biraz sonra tekrar deneyin.",
            )
            return self.form_invalid(form)

        if result.status != "sent":
            form.add_error(
                None,
                "Doğrulama e-postası şu anda gönderilemedi. "
                "Lütfen biraz sonra tekrar deneyin.",
            )
            return self.form_invalid(form)

        return super().form_valid(form)


@method_decorator(
    role_required(User.UserType.USER),
    name="dispatch",
)
class EmailChangePendingView(TemplateView):
    template_name = "accounts/email_change_pending.html"


@role_required(User.UserType.USER)
@no_referrer
@require_http_methods(["GET", "POST"])
def email_change_confirm(request, token):
    resolved = resolve_email_change_token(token)

    if resolved is None:
        return render(
            request,
            "accounts/email_change_confirm.html",
            {
                "token_valid": False,
            },
            status=400,
        )

    token_user, new_email = resolved

    if token_user.pk != request.user.pk:
        raise PermissionDenied

    if request.method == "GET":
        return render(
            request,
            "accounts/email_change_confirm.html",
            {
                "token_valid": True,
                "new_email": new_email,
            },
        )

    changed_user = apply_email_change_token(
        token,
        keep_session_key=(
            request.session.session_key
        ),
    )

    if changed_user is None or changed_user.pk != request.user.pk:
        return render(
            request,
            "accounts/email_change_confirm.html",
            {
                "token_valid": False,
            },
            status=400,
        )

    messages.success(
        request,
        "E-posta adresiniz başarıyla değiştirildi.",
    )
    request.session.cycle_key()
    return redirect("accounts:email_change_complete")


@method_decorator(
    role_required(User.UserType.USER),
    name="dispatch",
)
class EmailChangeCompleteView(TemplateView):
    template_name = "accounts/email_change_complete.html"
