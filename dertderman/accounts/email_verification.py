import json
import secrets
import uuid
from datetime import timedelta
from hashlib import sha256

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from notifications.email_service import (
    EmailConfigurationError,
    build_recipient_hash,
    send_email,
)
from notifications.models import EmailOutbox
from notifications.outbox_service import (
    EmailPayload,
    OutboxBusinessCancellation,
    OutboxConfigurationError,
)

from .models import User


TOKEN_SALT = "accounts.email-verification.v1"
REQUEST_STATE_SALT = "accounts.email_verification.request_state.v1"
MAX_TOKEN_LENGTH = 1024
EMAIL_VERIFICATION_ALREADY_VERIFIED = "EMAIL_VERIFICATION_ALREADY_VERIFIED"
EMAIL_VERIFICATION_USER_INELIGIBLE = "EMAIL_VERIFICATION_USER_INELIGIBLE"
EMAIL_VERIFICATION_STATE_CHANGED = "EMAIL_VERIFICATION_STATE_CHANGED"


class EmailVerificationConfigurationError(OutboxConfigurationError):
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


def _normalized_email(email: str) -> str:
    return User.objects.normalize_email((email or "").strip()).casefold()


def _is_email_verification_eligible(user: User | None) -> bool:
    return bool(
        user
        and user.pk
        and user.user_type == User.UserType.USER
        and user.is_active
        and not user.is_verified
        and not user.is_permanently_closed
        and _normalized_email(user.email)
    )


def build_email_verification_request_state_hash(user: User) -> str:
    canonical_state = json.dumps(
        [
            1,
            str(user.pk),
            _normalized_email(user.email),
            user.password or "",
            bool(user.is_verified),
            bool(user.is_active),
            user.user_type,
            bool(user.is_permanently_closed),
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


class _FixedTimestampSigner(signing.TimestampSigner):
    """TimestampSigner-compatible signer fixed to an outbox issue time."""

    def __init__(self, *, issued_at, **kwargs):
        super().__init__(**kwargs)
        self.issued_at = issued_at

    def timestamp(self):
        return signing.b62_encode(int(self.issued_at.timestamp()))


def make_email_verification_token(user: User, *, issued_at=None) -> str:
    if not user.pk:
        raise ValueError("User must be saved before creating a verification token.")

    if user.user_type != User.UserType.USER:
        raise ValueError("Email verification token is only valid for USER accounts.")

    if user.is_verified:
        raise ValueError("Verified users do not need a verification token.")

    value = f"{user.pk}:{_verification_state_digest(user)}"
    if issued_at is None:
        signer = signing.TimestampSigner(salt=TOKEN_SALT)
    else:
        signer = _FixedTimestampSigner(
            salt=TOKEN_SALT,
            issued_at=issued_at,
        )
    return signer.sign(value)


def _token_max_age() -> int:
    try:
        value = int(getattr(settings, "EMAIL_VERIFICATION_TIMEOUT", 1800))
    except (TypeError, ValueError) as exc:
        raise EmailVerificationConfigurationError(
            "EMAIL_VERIFICATION_TIMEOUT must be an integer number of seconds."
        ) from exc

    if value <= 0:
        raise EmailVerificationConfigurationError(
            "EMAIL_VERIFICATION_TIMEOUT must be a positive integer."
        )

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


def build_email_verification_url(user: User, *, issued_at=None) -> str:
    base_url = (
        getattr(settings, "SITE_BASE_URL", "")
        or ""
    ).strip().rstrip("/")

    if not base_url:
        raise EmailVerificationConfigurationError(
            "SITE_BASE_URL is required for verification links."
        )

    token = make_email_verification_token(user, issued_at=issued_at)
    path = reverse(
        "accounts:email_verification_confirm",
        kwargs={"token": token},
    )
    return f"{base_url}{path}"


def enqueue_email_verification(user: User):
    if not _is_email_verification_eligible(user):
        raise ValueError("User is not eligible for email verification.")

    now = timezone.now()
    outbox_id = uuid.uuid4()
    return EmailOutbox.objects.create(
        id=outbox_id,
        kind=EmailOutbox.Kind.EMAIL_VERIFICATION,
        status=EmailOutbox.Status.PENDING,
        recipient_user=user,
        notification=None,
        recipient_hash=build_recipient_hash(_normalized_email(user.email)),
        request_state_hash=build_email_verification_request_state_hash(user),
        provider="resend",
        provider_idempotency_key=f"dertderman/email/{outbox_id}",
        template_version=1,
        token_issued_at=now,
        expires_at=now + timedelta(seconds=_token_max_age()),
        available_at=now,
    )


def _email_verification_user_for_outbox(outbox, *, now=None):
    now = now or timezone.now()
    if outbox.kind != EmailOutbox.Kind.EMAIL_VERIFICATION:
        raise EmailVerificationConfigurationError(
            "Invalid email-verification outbox kind."
        )
    if outbox.expires_at is None or outbox.expires_at <= now:
        raise OutboxBusinessCancellation("OUTBOX_EXPIRED")
    if outbox.recipient_user_id is None:
        raise OutboxBusinessCancellation(EMAIL_VERIFICATION_USER_INELIGIBLE)

    user = User.objects.filter(pk=outbox.recipient_user_id).first()
    if user is None:
        raise OutboxBusinessCancellation(EMAIL_VERIFICATION_USER_INELIGIBLE)
    if user.is_verified:
        raise OutboxBusinessCancellation(EMAIL_VERIFICATION_ALREADY_VERIFIED)
    if not _is_email_verification_eligible(user):
        raise OutboxBusinessCancellation(EMAIL_VERIFICATION_USER_INELIGIBLE)

    current_state_hash = build_email_verification_request_state_hash(user)
    if not secrets.compare_digest(outbox.request_state_hash, current_state_hash):
        raise OutboxBusinessCancellation(EMAIL_VERIFICATION_STATE_CHANGED)

    current_recipient_hash = build_recipient_hash(_normalized_email(user.email))
    if not secrets.compare_digest(outbox.recipient_hash, current_recipient_hash):
        raise OutboxBusinessCancellation(EMAIL_VERIFICATION_STATE_CHANGED)
    return user


def email_verification_cancellation_code(outbox, *, now=None):
    try:
        _email_verification_user_for_outbox(outbox, now=now)
    except OutboxBusinessCancellation as exc:
        return exc.code
    return None


def _render_email_verification_payload(user: User, *, issued_at=None):
    verification_url = build_email_verification_url(user, issued_at=issued_at)
    context = {
        "verification_url": verification_url,
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
        subject="E-posta adresinizi doğrulayın | DertDerman",
        html_body=render_to_string("emails/email_verification.html", context),
        text_body=render_to_string("emails/email_verification.txt", context),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", ""),
        reply_to=getattr(settings, "EMAIL_REPLY_TO", ""),
    )


def render_email_verification_outbox(outbox):
    user = _email_verification_user_for_outbox(outbox)
    if outbox.template_version != 1 or outbox.token_issued_at is None:
        raise EmailVerificationConfigurationError(
            "Unsupported email-verification template recipe."
        )
    return _render_email_verification_payload(
        user,
        issued_at=outbox.token_issued_at,
    )


def send_verification_email(user: User):
    if user.user_type != User.UserType.USER:
        raise ValueError("Verification email is only valid for USER accounts.")

    if user.is_verified:
        raise ValueError("Verified users do not need a verification email.")

    payload = _render_email_verification_payload(user)

    event_key = (
        "account:email-verification:"
        f"{user.pk}:"
        f"{_verification_state_digest(user)[:20]}"
    )

    try:
        return send_email(
            recipient_email=payload.recipient_email,
            subject=payload.subject,
            html_body=payload.html_body,
            text_body=payload.text_body,
            event_key=event_key,
            from_email=payload.from_email,
            reply_to=payload.reply_to,
        )
    except EmailConfigurationError:
        raise
