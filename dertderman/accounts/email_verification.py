from hashlib import sha256

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.crypto import constant_time_compare

from notifications.email_service import (
    EmailConfigurationError,
    send_email,
)

from .models import User


TOKEN_SALT = "accounts.email-verification.v1"
MAX_TOKEN_LENGTH = 1024


class EmailVerificationConfigurationError(RuntimeError):
    """Raised when verification email settings are incomplete."""


def _verification_state_digest(user: User) -> str:
    email = (user.email or "").strip().casefold()
    material = "\0".join(
        (
            str(user.pk),
            email,
            user.password or "",
            "1" if user.is_verified else "0",
        )
    )
    return sha256(material.encode("utf-8")).hexdigest()


def make_email_verification_token(user: User) -> str:
    if not user.pk:
        raise ValueError("User must be saved before creating a verification token.")

    if user.user_type != User.UserType.USER:
        raise ValueError("Email verification token is only valid for USER accounts.")

    if user.is_verified:
        raise ValueError("Verified users do not need a verification token.")

    value = f"{user.pk}:{_verification_state_digest(user)}"
    return signing.TimestampSigner(salt=TOKEN_SALT).sign(value)


def _token_max_age() -> int:
    try:
        value = int(getattr(settings, "EMAIL_VERIFICATION_TIMEOUT", 86400))
    except (TypeError, ValueError) as exc:
        raise EmailVerificationConfigurationError(
            "EMAIL_VERIFICATION_TIMEOUT must be an integer number of seconds."
        ) from exc

    if value <= 0:
        return value

    return value


def resolve_email_verification_token(
    token: str,
    *,
    for_update: bool = False,
) -> User | None:
    token = (token or "").strip()

    if not token or len(token) > MAX_TOKEN_LENGTH:
        return None

    signer = signing.TimestampSigner(salt=TOKEN_SALT)

    try:
        unsigned = signer.unsign(
            token,
            max_age=_token_max_age(),
        )
    except signing.BadSignature:
        return None

    try:
        user_id_text, _digest = unsigned.split(":", 1)
        user_id = int(user_id_text)
    except (TypeError, ValueError):
        return None

    queryset = User.objects.filter(
        pk=user_id,
        user_type=User.UserType.USER,
        is_active=True,
    )

    if for_update:
        queryset = queryset.select_for_update()

    user = queryset.first()

    if not user or user.is_verified:
        return None

    expected = f"{user.pk}:{_verification_state_digest(user)}"

    if not constant_time_compare(unsigned, expected):
        return None

    return user


@transaction.atomic
def verify_email_verification_token(token: str) -> User | None:
    user = resolve_email_verification_token(
        token,
        for_update=True,
    )

    if user is None:
        return None

    user.is_verified = True
    user.save(update_fields=("is_verified",))
    return user


def build_email_verification_url(user: User) -> str:
    base_url = (
        getattr(settings, "SITE_BASE_URL", "")
        or ""
    ).strip().rstrip("/")

    if not base_url:
        raise EmailVerificationConfigurationError(
            "SITE_BASE_URL is required for verification links."
        )

    token = make_email_verification_token(user)
    path = reverse(
        "accounts:email_verification_confirm",
        kwargs={"token": token},
    )
    return f"{base_url}{path}"


def send_verification_email(user: User):
    if user.user_type != User.UserType.USER:
        raise ValueError("Verification email is only valid for USER accounts.")

    if user.is_verified:
        raise ValueError("Verified users do not need a verification email.")

    verification_url = build_email_verification_url(user)

    context = {
        "user": user,
        "verification_url": verification_url,
        "support_email": getattr(settings, "SUPPORT_EMAIL", "destek@dertderman.com"),
        "support_phone": getattr(settings, "SUPPORT_PHONE", "+90 850 532 2206"),
        "support_hours": getattr(settings, "SUPPORT_HOURS", "Hafta içi 09:00 - 18:00"),
    }

    html_body = render_to_string(
        "emails/email_verification.html",
        context,
    )
    text_body = render_to_string(
        "emails/email_verification.txt",
        context,
    )

    event_key = (
        "account:email-verification:"
        f"{user.pk}:"
        f"{_verification_state_digest(user)[:20]}"
    )

    try:
        return send_email(
            recipient_email=user.email,
            subject="E-posta adresinizi doğrulayın | DertDerman",
            html_body=html_body,
            text_body=text_body,
            event_key=event_key,
        )
    except EmailConfigurationError:
        raise
