import logging

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from django.views.generic import FormView, TemplateView

from core.decorators import role_required
from notifications.email_service import EmailServiceError

from .email_change import (
    apply_email_change_token,
    normalize_email,
    resolve_email_change_token,
    send_email_change_verification,
)
from .models import User


logger = logging.getLogger(__name__)


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

    def form_valid(self, form):
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

    changed_user = apply_email_change_token(token)

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
    return redirect("accounts:email_change_complete")


@method_decorator(
    role_required(User.UserType.USER),
    name="dispatch",
)
class EmailChangeCompleteView(TemplateView):
    template_name = "accounts/email_change_complete.html"
