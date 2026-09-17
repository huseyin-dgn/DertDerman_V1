from django import forms
from django.contrib.auth.views import (
    INTERNAL_RESET_SESSION_TOKEN,
    PasswordResetCompleteView as DjangoPasswordResetCompleteView,
    PasswordResetConfirmView as DjangoPasswordResetConfirmView,
)
from django.db import transaction
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import (
    FormView,
    TemplateView,
)

from core.session_security import revoke_user_sessions
from core.rate_limit import (
    client_ip,
    consume_rate_limit,
)

from .password_reset import (
    password_reset_token_generator,
    request_password_reset,
)
from .models import User


GENERIC_RESET_MESSAGE = (
    "Eğer bu e-posta adresiyle kayıtlı bir hesap varsa "
    "şifre sıfırlama bağlantısı gönderildi."
)


PASSWORD_RESET_EMAIL_LIMIT = 5
PASSWORD_RESET_IP_LIMIT = 20
PASSWORD_RESET_WINDOW_SECONDS = 15 * 60


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(
        label="E-posta",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
            }
        ),
    )


@method_decorator(
    never_cache,
    name="dispatch",
)
class PasswordResetRequestView(FormView):
    template_name = (
        "accounts/password_reset_request.html"
    )
    form_class = PasswordResetRequestForm
    success_url = reverse_lazy(
        "accounts:password_reset_done"
    )

    def form_valid(self, form):
        email = form.cleaned_data["email"].strip().casefold()
        ip = client_ip(self.request)
        email_decision = consume_rate_limit(
            scope="password-reset-email",
            identifier=email,
            limit=PASSWORD_RESET_EMAIL_LIMIT,
            window_seconds=PASSWORD_RESET_WINDOW_SECONDS,
        )
        ip_decision = consume_rate_limit(
            scope="password-reset-ip",
            identifier=ip,
            limit=PASSWORD_RESET_IP_LIMIT,
            window_seconds=PASSWORD_RESET_WINDOW_SECONDS,
        )
        # Enumeration direnci: limit asildiginda da public davranis ayni kalir.
        if email_decision.allowed and ip_decision.allowed:
            request_password_reset(email)
        return super().form_valid(form)


@method_decorator(
    never_cache,
    name="dispatch",
)
class PasswordResetDoneView(TemplateView):
    template_name = (
        "accounts/password_reset_done.html"
    )

    def get_context_data(
        self,
        **kwargs,
    ):
        context = super().get_context_data(
            **kwargs
        )
        context["generic_reset_message"] = (
            GENERIC_RESET_MESSAGE
        )
        return context


@method_decorator(
    never_cache,
    name="dispatch",
)
class SecurePasswordResetConfirmView(
    DjangoPasswordResetConfirmView
):
    token_generator = password_reset_token_generator
    template_name = (
        "accounts/password_reset_confirm.html"
    )
    success_url = reverse_lazy(
        "accounts:password_reset_complete"
    )
    post_reset_login = False

    def form_valid(self, form):
        with transaction.atomic():
            user = (
                User.objects
                .select_for_update()
                .filter(pk=self.user.pk)
                .first()
            )
            token = self.request.session.get(INTERNAL_RESET_SESSION_TOKEN)
            if not self.token_generator.check_token(user, token):
                self.validlink = False
                return self.render_to_response(self.get_context_data())

            form.user = user

            response = super().form_valid(
                form
            )

            revoke_user_sessions(
                user.pk
            )

            return response


@method_decorator(
    never_cache,
    name="dispatch",
)
class SecurePasswordResetCompleteView(
    DjangoPasswordResetCompleteView
):
    template_name = (
        "accounts/password_reset_complete.html"
    )
