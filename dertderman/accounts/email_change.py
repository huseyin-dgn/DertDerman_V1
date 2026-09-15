from hashlib import sha256

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.crypto import constant_time_compare

from notifications.email_service import send_email

from .models import User


TOKEN_SALT = "accounts.email-change.v1"
MAX_TOKEN_LENGTH = 2048


class EmailChangeConfigurationError(RuntimeError):
    """Raised when email-change configuration is invalid."""


def normalize_email(value: str) -> str:
    value = (value or "").strip()
    try:
        validate_email(value)
    except ValidationError as exc:
        raise ValueError("Invalid email address.") from exc
    return User.objects.normalize_email(value)


def _state_digest(user: User) -> str:
    material = "\0".join(
        (
            str(user.pk),
            (user.email or "").strip().casefold(),
            user.password or "",
            "1" if user.is_verified else "0",
            "1" if user.is_active else "0",
        )
    )
    return sha256(material.encode("utf-8")).hexdigest()


def _token_max_age() -> int:
    try:
        value = int(getattr(settings, "EMAIL_CHANGE_TIMEOUT", 600))
    except (TypeError, ValueError) as exc:
        raise EmailChangeConfigurationError(
            "EMAIL_CHANGE_TIMEOUT must be an integer number of seconds."
        ) from exc
    return value


def _eligible_user_queryset():
    return User.objects.filter(
        user_type=User.UserType.USER,
        is_active=True,
        is_verified=True,
        is_permanently_closed=False,
    )


def _email_in_use(email: str, *, exclude_user_id=None) -> bool:
    queryset = User.objects.filter(email__iexact=email)
    if exclude_user_id is not None:
        queryset = queryset.exclude(pk=exclude_user_id)
    return queryset.exists()


def make_email_change_token(user: User, new_email: str) -> str:
    if not user.pk:
        raise ValueError("User must be saved before creating an email-change token.")

    if (
        not user.can_perform_user_mutations
        or not user.is_verified
    ):
        raise ValueError("User is not eligible for email change.")

    new_email = normalize_email(new_email)

    if new_email.casefold() == (user.email or "").strip().casefold():
        raise ValueError("New email must be different from the current email.")

    if _email_in_use(new_email, exclude_user_id=user.pk):
        raise ValueError("Email address is already in use.")

    payload = {
        "uid": user.pk,
        "old_email": (user.email or "").strip(),
        "new_email": new_email,
        "state": _state_digest(user),
    }

    return signing.dumps(
        payload,
        salt=TOKEN_SALT,
        compress=True,
    )


def resolve_email_change_token(
    token: str,
    *,
    for_update: bool = False,
) -> tuple[User, str] | None:
    token = (token or "").strip()

    if not token or len(token) > MAX_TOKEN_LENGTH:
        return None

    try:
        payload = signing.loads(
            token,
            salt=TOKEN_SALT,
            max_age=_token_max_age(),
        )
    except signing.BadSignature:
        return None

    if not isinstance(payload, dict):
        return None

    try:
        user_id = int(payload["uid"])
        old_email = normalize_email(payload["old_email"])
        new_email = normalize_email(payload["new_email"])
        token_state = str(payload["state"])
    except (KeyError, TypeError, ValueError):
        return None

    queryset = _eligible_user_queryset().filter(pk=user_id)
    if for_update:
        queryset = queryset.select_for_update()

    user = queryset.first()
    if user is None:
        return None

    if not user.can_perform_user_mutations:
        return None

    current_email = normalize_email(user.email)

    if current_email.casefold() != old_email.casefold():
        return None

    if new_email.casefold() == current_email.casefold():
        return None

    if not constant_time_compare(token_state, _state_digest(user)):
        return None

    if _email_in_use(new_email, exclude_user_id=user.pk):
        return None

    return user, new_email


def apply_email_change_token(token: str) -> User | None:
    try:
        with transaction.atomic():
            resolved = resolve_email_change_token(
                token,
                for_update=True,
            )

            if resolved is None:
                return None

            user, new_email = resolved

            if _email_in_use(new_email, exclude_user_id=user.pk):
                return None

            user.email = new_email
            user.is_verified = True
            user.save(update_fields=("email", "is_verified"))

            return user
    except IntegrityError:
        return None


def _site_base_url() -> str:
    base_url = (
        getattr(settings, "SITE_BASE_URL", "")
        or ""
    ).strip().rstrip("/")

    if not base_url:
        raise EmailChangeConfigurationError(
            "SITE_BASE_URL is required for email-change links."
        )

    return base_url


def build_email_change_url(user: User, new_email: str) -> tuple[str, str]:
    token = make_email_change_token(user, new_email)
    path = reverse(
        "accounts:email_change_confirm",
        kwargs={"token": token},
    )
    return f"{_site_base_url()}{path}", token


def send_email_change_verification(user: User, new_email: str):
    new_email = normalize_email(new_email)
    confirmation_url, token = build_email_change_url(user, new_email)

    context = {
        "user": user,
        "new_email": new_email,
        "confirmation_url": confirmation_url,
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
        "emails/email_change_verification.html",
        context,
    )
    text_body = render_to_string(
        "emails/email_change_verification.txt",
        context,
    )

    token_digest = sha256(token.encode("utf-8")).hexdigest()[:20]
    event_key = f"account:email-change:{user.pk}:{token_digest}"

    return send_email(
        recipient_email=new_email,
        subject="E-posta değişikliğini onaylayın | DertDerman",
        html_body=html_body,
        text_body=text_body,
        event_key=event_key,
    )
