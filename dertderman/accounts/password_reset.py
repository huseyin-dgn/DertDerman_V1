import json
import logging
import secrets
import uuid
from datetime import timedelta, timezone as datetime_timezone

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from notifications.email_service import build_recipient_hash
from notifications.models import EmailOutbox
from notifications.outbox_service import (
    EmailPayload,
    OutboxBusinessCancellation,
    OutboxConfigurationError,
)

from .models import User


logger = logging.getLogger(__name__)

REQUEST_STATE_SALT = "accounts.password_reset.request_state.v1"
PASSWORD_RESET_STATE_CHANGED = "PASSWORD_RESET_STATE_CHANGED"


class PasswordResetConfigurationError(OutboxConfigurationError):
    """Raised when password-reset rendering configuration is incomplete."""


class DertDermanPasswordResetTokenGenerator(PasswordResetTokenGenerator):
    """Django-compatible tokens whose timestamp can be fixed at enqueue time."""

    def make_token_at(self, user, issued_at):
        if issued_at is None:
            raise ValueError("Password-reset token issue time is required.")

        # Django 5.2.13 exposes no public timestamp-injection API. Reuse its
        # implementation seam so token format, HMAC and validation semantics
        # remain identical instead of duplicating Django's cryptography.
        if timezone.is_aware(issued_at):
            issued_at = issued_at.astimezone().replace(tzinfo=None)
        timestamp = self._num_seconds(issued_at)
        return self._make_token_with_timestamp(user, timestamp, self.secret)

    def check_token(self, user, token):
        if not _is_password_reset_eligible(user):
            return False
        return super().check_token(user, token)


password_reset_token_generator = DertDermanPasswordResetTokenGenerator()


def _site_base_url() -> str:
    base_url = (getattr(settings, "SITE_BASE_URL", "") or "").strip().rstrip("/")
    if not base_url:
        raise PasswordResetConfigurationError(
            "SITE_BASE_URL is required for password-reset links."
        )
    return base_url


def _normalized_email(email):
    return User.objects.normalize_email((email or "").strip()).casefold()


def _is_password_reset_eligible(user):
    return bool(
        user
        and user.pk
        and user.user_type == User.UserType.USER
        and user.is_active
        and user.is_verified
        and _normalized_email(user.email)
    )


def _eligible_user(email: str) -> User | None:
    normalized = _normalized_email(email)
    if not normalized:
        return None
    return (
        User.objects.filter(
            email__iexact=normalized,
            user_type=User.UserType.USER,
            is_active=True,
            is_verified=True,
        )
        .first()
    )


def _last_login_state(last_login):
    if last_login is None:
        return ""
    if timezone.is_aware(last_login):
        last_login = last_login.astimezone(datetime_timezone.utc)
    return last_login.isoformat(timespec="microseconds")


def build_password_reset_request_state_hash(user: User) -> str:
    canonical_state = json.dumps(
        [
            1,
            str(user.pk),
            user.password,
            _last_login_state(user.last_login),
            _normalized_email(user.email),
            bool(user.is_active),
            bool(user.is_verified),
            user.user_type,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return salted_hmac(
        REQUEST_STATE_SALT,
        canonical_state,
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()


def build_password_reset_url(user: User, *, issued_at) -> tuple[str, str]:
    if not _is_password_reset_eligible(user):
        raise ValueError("User is not eligible for password reset.")

    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = password_reset_token_generator.make_token_at(user, issued_at)
    path = reverse(
        "accounts:password_reset_confirm",
        kwargs={"uidb64": uidb64, "token": token},
    )
    return f"{_site_base_url()}{path}", token


def _password_reset_user_for_outbox(outbox, *, now=None):
    now = now or timezone.now()
    if outbox.kind != EmailOutbox.Kind.PASSWORD_RESET:
        raise PasswordResetConfigurationError("Invalid password-reset outbox kind.")
    if outbox.recipient_user_id is None:
        raise OutboxBusinessCancellation("PASSWORD_RESET_NOOP")
    if outbox.expires_at is None or outbox.expires_at <= now:
        raise OutboxBusinessCancellation("PASSWORD_RESET_EXPIRED")

    user = User.objects.filter(pk=outbox.recipient_user_id).first()
    if not _is_password_reset_eligible(user):
        raise OutboxBusinessCancellation(PASSWORD_RESET_STATE_CHANGED)

    current_state_hash = build_password_reset_request_state_hash(user)
    if not secrets.compare_digest(outbox.request_state_hash, current_state_hash):
        raise OutboxBusinessCancellation(PASSWORD_RESET_STATE_CHANGED)

    current_recipient_hash = build_recipient_hash(_normalized_email(user.email))
    if not secrets.compare_digest(outbox.recipient_hash, current_recipient_hash):
        raise OutboxBusinessCancellation(PASSWORD_RESET_STATE_CHANGED)
    return user


def password_reset_cancellation_code(outbox, *, now=None):
    try:
        _password_reset_user_for_outbox(outbox, now=now)
    except OutboxBusinessCancellation as exc:
        return exc.code
    return None


def render_password_reset_outbox(outbox):
    user = _password_reset_user_for_outbox(outbox)
    if outbox.template_version != 1:
        raise PasswordResetConfigurationError(
            "Unsupported password-reset template version."
        )

    reset_url, _token = build_password_reset_url(
        user,
        issued_at=outbox.token_issued_at,
    )
    context = {
        "user": user,
        "reset_url": reset_url,
        "support_email": getattr(settings, "SUPPORT_EMAIL", "destek@dertderman.com"),
        "support_phone": getattr(settings, "SUPPORT_PHONE", "+90 850 532 2206"),
        "support_hours": getattr(
            settings,
            "SUPPORT_HOURS",
            "Hafta içi 09:00 - 18:00",
        ),
    }
    return EmailPayload(
        recipient_email=user.email,
        subject="Şifrenizi sıfırlayın | DertDerman",
        html_body=render_to_string("emails/password_reset.html", context),
        text_body=render_to_string("emails/password_reset.txt", context),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", ""),
        reply_to=getattr(settings, "EMAIL_REPLY_TO", ""),
    )


def request_password_reset(email: str):
    """Persist exactly one reset intent without exposing account existence."""
    normalized = _normalized_email(email)
    user = _eligible_user(normalized)
    now = timezone.now()
    outbox_id = uuid.uuid4()

    values = {
        "id": outbox_id,
        "kind": EmailOutbox.Kind.PASSWORD_RESET,
        "status": EmailOutbox.Status.PENDING,
        "recipient_user": None,
        "notification": None,
        "recipient_hash": "",
        "request_state_hash": "",
        "provider": "resend",
        "provider_idempotency_key": f"dertderman/email/{outbox_id}",
        "template_version": 1,
        "token_issued_at": None,
        "expires_at": None,
        "available_at": now,
    }
    if user is not None:
        values.update(
            recipient_user=user,
            recipient_hash=build_recipient_hash(_normalized_email(user.email)),
            request_state_hash=build_password_reset_request_state_hash(user),
            token_issued_at=now,
            expires_at=now
            + timedelta(seconds=int(getattr(settings, "PASSWORD_RESET_TIMEOUT", 300))),
        )

    try:
        with transaction.atomic():
            return EmailOutbox.objects.create(**values)
    except Exception as exc:
        # Public behavior remains generic. Never log the submitted address,
        # token material, canonical state, or a raw database error payload.
        logger.error(
            "Password reset enqueue failed: exception_type=%s",
            exc.__class__.__name__,
        )
        return None
