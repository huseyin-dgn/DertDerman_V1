import logging
from hashlib import sha256

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from notifications.email_service import EmailServiceError, send_email

from .models import User


logger = logging.getLogger(__name__)


class PasswordResetConfigurationError(RuntimeError):
    """Raised when password-reset URL configuration is incomplete."""


def _site_base_url() -> str:
    base_url = (
        getattr(settings, "SITE_BASE_URL", "")
        or ""
    ).strip().rstrip("/")

    if not base_url:
        raise PasswordResetConfigurationError(
            "SITE_BASE_URL is required for password-reset links."
        )

    return base_url


def _eligible_user(email: str) -> User | None:
    normalized = User.objects.normalize_email(
        (email or "").strip()
    )

    if not normalized:
        return None

    return (
        User.objects
        .filter(
            email__iexact=normalized,
            user_type=User.UserType.USER,
            is_active=True,
            is_verified=True,
        )
        .first()
    )


def build_password_reset_url(
    user: User,
) -> tuple[str, str]:
    if not user.pk:
        raise ValueError(
            "User must be saved before creating a password-reset token."
        )

    if user.user_type != User.UserType.USER:
        raise ValueError(
            "Password reset is only available for USER accounts here."
        )

    if not user.is_active or not user.is_verified:
        raise ValueError(
            "Password reset requires an active, verified USER account."
        )

    uidb64 = urlsafe_base64_encode(
        force_bytes(user.pk)
    )
    token = default_token_generator.make_token(
        user
    )

    path = reverse(
        "accounts:password_reset_confirm",
        kwargs={
            "uidb64": uidb64,
            "token": token,
        },
    )

    return f"{_site_base_url()}{path}", token


def send_password_reset_email(user: User):
    reset_url, token = build_password_reset_url(
        user
    )

    context = {
        "user": user,
        "reset_url": reset_url,
        "support_email": getattr(
            settings,
            "SUPPORT_EMAIL",
            "destek@dertderman.com",
        ),
        "support_phone": getattr(
            settings,
            "SUPPORT_PHONE",
            "+90 850 532 2206",
        ),
        "support_hours": getattr(
            settings,
            "SUPPORT_HOURS",
            "Hafta içi 09:00 - 18:00",
        ),
    }

    html_body = render_to_string(
        "emails/password_reset.html",
        context,
    )
    text_body = render_to_string(
        "emails/password_reset.txt",
        context,
    )

    token_digest = sha256(
        token.encode("utf-8")
    ).hexdigest()[:20]

    return send_email(
        recipient_email=user.email,
        subject="Şifrenizi sıfırlayın | DertDerman",
        html_body=html_body,
        text_body=text_body,
        event_key=(
            "account:password-reset:"
            f"{user.pk}:{token_digest}"
        ),
    )


def request_password_reset(
    email: str,
):
    """
    Always returns without revealing whether the account exists.

    Provider delivery failures are intentionally swallowed here so the
    public response cannot be used to distinguish registered addresses.
    """
    user = _eligible_user(email)

    if user is None:
        return None

    try:
        return send_password_reset_email(
            user
        )
    except EmailServiceError as exc:
        logger.warning(
            (
                "Password reset email delivery failed: "
                "user_id=%s exception_type=%s"
            ),
            user.pk,
            exc.__class__.__name__,
        )
        return None
