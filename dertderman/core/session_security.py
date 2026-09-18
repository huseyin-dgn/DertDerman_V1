import time

from django.conf import settings
from django.contrib.auth import (
    SESSION_KEY,
    get_user_model,
    logout,
)
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from .models import AuthenticatedSession


SESSION_STARTED_AT_KEY = "_dd_auth_started_at"
SESSION_LAST_SEEN_AT_KEY = "_dd_auth_last_seen_at"
SESSION_ROLE_KEY = "_dd_auth_role"
SESSION_REAUTH_AT_KEY = "_dd_auth_reauth_at"


def _positive_int(value):
    if isinstance(value, bool):
        return None

    try:
        value = int(value)
    except (TypeError, ValueError):
        return None

    return value if value > 0 else None


def mark_reauthenticated(
    session,
    *,
    now=None,
):
    timestamp = (
        int(time.time())
        if now is None
        else _positive_int(now)
    )

    if timestamp is None or timestamp <= 0:
        return False

    session[SESSION_REAUTH_AT_KEY] = timestamp
    return True


def has_recent_reauthentication(
    session,
    *,
    now=None,
):
    max_age = _positive_int(
        getattr(
            settings,
            "AUTH_SESSION_REAUTH_MAX_AGE_SECONDS",
            5 * 60,
        )
    )

    authenticated_at = _positive_int(
        session.get(
            SESSION_REAUTH_AT_KEY
        )
    )

    current_time = (
        int(time.time())
        if now is None
        else _positive_int(now)
    )

    if (
        max_age is None
        or authenticated_at is None
        or current_time is None
        or current_time < authenticated_at
    ):
        return False

    return (
        current_time - authenticated_at
        < max_age
    )


def _policy_for(user):
    role = (
        getattr(user, "user_type", "")
        or ""
    ).strip().upper()

    policies = getattr(
        settings,
        "AUTH_SESSION_SECURITY_POLICIES",
        {},
    )

    policy = policies.get(role)

    if not isinstance(policy, dict):
        return role, None

    idle_seconds = _positive_int(
        policy.get("idle_seconds")
    )

    absolute_seconds = _positive_int(
        policy.get("absolute_seconds")
    )

    if (
        idle_seconds is None
        or absolute_seconds is None
        or idle_seconds > absolute_seconds
    ):
        return role, None

    return role, (
        idle_seconds,
        absolute_seconds,
    )


def _max_active_sessions_for(role):
    policies = getattr(
        settings,
        "AUTH_SESSION_MAX_ACTIVE_SESSIONS",
        {},
    )

    if not isinstance(policies, dict):
        return None

    return _positive_int(
        policies.get(role)
    )


def _initialize_session(
    session,
    *,
    role,
    now,
):
    session[SESSION_STARTED_AT_KEY] = now
    session[SESSION_LAST_SEEN_AT_KEY] = now
    session[SESSION_ROLE_KEY] = role


def _register_authenticated_session(
    *,
    user,
    session,
    role,
    touch=False,
):
    session_key = session.session_key

    if not session_key:
        return False

    max_active = _max_active_sessions_for(
        role
    )

    if max_active is None:
        return False

    now = timezone.now()
    User = get_user_model()

    with transaction.atomic():
        current_user = (
            User.objects
            .select_for_update()
            .filter(pk=user.pk)
            .only("pk")
            .first()
        )

        if current_user is None:
            return False

        if not Session.objects.filter(
            session_key=session_key,
            expire_date__gt=now,
        ).exists():
            return False

        registered = (
            AuthenticatedSession.objects
            .select_for_update()
            .filter(session_id=session_key)
            .first()
        )

        if registered is None:
            AuthenticatedSession.objects.create(
                session_id=session_key,
                user_id=user.pk,
                role=role,
            )

        elif (
            registered.user_id != user.pk
            or registered.role != role
        ):
            return False

        elif touch:
            AuthenticatedSession.objects.filter(
                session_id=session_key
            ).update(
                last_seen_at=now
            )

        # Limit yalnız yeni loginlerde değil, migration ile
        # backfill edilmiş mevcut oturumlarda da uygulanır. Böylece
        # deployment öncesinden limit üstü session'lar ilk kullanımda
        # güvenli biçimde limite yakınsar.
        active = (
            AuthenticatedSession.objects
            .filter(
                user_id=user.pk,
                session__expire_date__gt=now,
            )
        )

        overflow = (
            active.count()
            - max_active
        )

        if overflow <= 0:
            return True

        victim_keys = list(
            active
            .exclude(
                session_id=session_key
            )
            .order_by(
                "created_at",
                "session_id",
            )
            .values_list(
                "session_id",
                flat=True,
            )[:overflow]
        )

        if len(victim_keys) != overflow:
            return False

        Session.objects.filter(
            session_key__in=victim_keys
        ).delete()

    return True


def revoke_user_sessions(
    user_id,
    *,
    keep_session_key=None,
):
    """
    Revoke sessions through the indexed ownership registry.

    This is O(number of sessions owned by the target account),
    rather than O(all sessions in the application).
    """
    registry = (
        AuthenticatedSession.objects
        .filter(user_id=user_id)
    )

    if keep_session_key:
        registry = registry.exclude(
            session_id=keep_session_key
        )

    session_keys = list(
        registry.values_list(
            "session_id",
            flat=True,
        )
    )

    if not session_keys:
        return 0

    Session.objects.filter(
        session_key__in=session_keys
    ).delete()

    return len(session_keys)


class SessionSecurityMiddleware:
    """
    Enforces server-side authentication-session limits and
    maintains the indexed authenticated-session registry.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(
            settings,
            "AUTH_SESSION_SECURITY_ENABLED",
            False,
        ):
            return self.get_response(request)

        session = getattr(
            request,
            "session",
            None,
        )

        user = getattr(
            request,
            "user",
            None,
        )

        if session is None or user is None:
            return self.get_response(request)

        if not user.is_authenticated:
            if SESSION_KEY in session:
                session.flush()

            response = self.get_response(
                request
            )

            post_user = getattr(
                request,
                "user",
                None,
            )

            if (
                post_user is not None
                and post_user.is_authenticated
            ):
                role, policy = _policy_for(
                    post_user
                )

                if policy is None:
                    logout(request)
                    return response

                _initialize_session(
                    session,
                    role=role,
                    now=int(time.time()),
                )

                # Bu branch gercek bir login isteginin hemen
                # sonrasidir. Legacy session initialization ise
                # yeniden kimlik dogrulamis kabul edilmez.
                mark_reauthenticated(
                    session
                )

                if not _register_authenticated_session(
                    user=post_user,
                    session=session,
                    role=role,
                    touch=True,
                ):
                    logout(request)

            return response

        role, policy = _policy_for(user)

        if policy is None:
            logout(request)
            return self.get_response(
                request
            )

        now = int(time.time())

        metadata_keys = (
            SESSION_STARTED_AT_KEY,
            SESSION_LAST_SEEN_AT_KEY,
            SESSION_ROLE_KEY,
        )

        present = tuple(
            key in session
            for key in metadata_keys
        )

        if not any(present):
            # Pre-hardening sessions are registered on their first
            # authenticated request. The migration also backfills
            # already-persisted authenticated sessions.
            _initialize_session(
                session,
                role=role,
                now=now,
            )

            if not _register_authenticated_session(
                user=user,
                session=session,
                role=role,
                touch=True,
            ):
                logout(request)

            return self.get_response(
                request
            )

        if not all(present):
            logout(request)
            return self.get_response(
                request
            )

        started_at = _positive_int(
            session.get(
                SESSION_STARTED_AT_KEY
            )
        )

        last_seen_at = _positive_int(
            session.get(
                SESSION_LAST_SEEN_AT_KEY
            )
        )

        stored_role = (
            session.get(
                SESSION_ROLE_KEY
            )
            or ""
        ).strip().upper()

        if (
            started_at is None
            or last_seen_at is None
            or stored_role != role
            or now < started_at
            or now < last_seen_at
        ):
            logout(request)
            return self.get_response(
                request
            )

        (
            idle_seconds,
            absolute_seconds,
        ) = policy

        if (
            now - started_at >= absolute_seconds
            or now - last_seen_at >= idle_seconds
        ):
            logout(request)
            return self.get_response(
                request
            )

        touch_seconds = _positive_int(
            getattr(
                settings,
                "AUTH_SESSION_ACTIVITY_TOUCH_SECONDS",
                60,
            )
        )

        if touch_seconds is None:
            logout(request)
            return self.get_response(
                request
            )

        touch_due = (
            now - last_seen_at
            >= touch_seconds
        )

        if not _register_authenticated_session(
            user=user,
            session=session,
            role=role,
            touch=touch_due,
        ):
            logout(request)
            return self.get_response(
                request
            )

        if touch_due:
            session[
                SESSION_LAST_SEEN_AT_KEY
            ] = now

        session_key_before_view = (
            session.session_key
        )

        response = self.get_response(
            request
        )

        post_user = getattr(
            request,
            "user",
            None,
        )

        if (
            post_user is None
            or not post_user.is_authenticated
        ):
            return response

        post_role, post_policy = _policy_for(
            post_user
        )

        if (
            post_policy is None
            or post_role != role
        ):
            logout(request)
            return response

        # Password changes and e-mail changes can rotate the
        # session key inside the view. Register that new key before
        # SessionMiddleware completes the response.
        if (
            session.session_key
            != session_key_before_view
        ):
            if not _register_authenticated_session(
                user=post_user,
                session=session,
                role=post_role,
                touch=True,
            ):
                logout(request)

        return response
