import time

from django.conf import settings
from django.contrib.auth import SESSION_KEY, logout
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core import signing


SESSION_STARTED_AT_KEY = "_dd_auth_started_at"
SESSION_LAST_SEEN_AT_KEY = "_dd_auth_last_seen_at"
SESSION_ROLE_KEY = "_dd_auth_role"


def _positive_int(value):
    if isinstance(value, bool):
        return None

    try:
        value = int(value)
    except (TypeError, ValueError):
        return None

    return value if value > 0 else None


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


def _initialize_session(
    session,
    *,
    role,
    now,
):
    session[SESSION_STARTED_AT_KEY] = now
    session[SESSION_LAST_SEEN_AT_KEY] = now
    session[SESSION_ROLE_KEY] = role


def _strict_decode_session_record(session):
    store = SessionStore(
        session_key=session.session_key
    )

    return signing.loads(
        session.session_data,
        salt=store.key_salt,
        serializer=store.serializer,
    )


def revoke_user_sessions(
    user_id,
    *,
    keep_session_key=None,
):
    """
    Immediately revoke DB-backed authenticated sessions for one
    account.

    Corrupt/unverifiable session rows are deleted fail-closed.
    An explicitly supplied current session is preserved only when
    it successfully decodes as belonging to the target user.
    """
    target = str(user_id)
    deleted = 0

    queryset = Session.objects.all().only(
        "session_key",
        "session_data",
    )

    for session in queryset.iterator(
        chunk_size=500
    ):
        try:
            decoded = _strict_decode_session_record(
                session
            )
        except Exception:
            session.delete()
            deleted += 1
            continue

        if decoded.get(SESSION_KEY) != target:
            continue

        if (
            keep_session_key
            and session.session_key
            == keep_session_key
        ):
            continue

        session.delete()
        deleted += 1

    return deleted


class SessionSecurityMiddleware:
    """
    Enforces server-side authentication-session limits.

    SESSION_COOKIE_AGE is not treated as an absolute login
    lifetime. These timestamps remain fixed independently of
    ordinary session modifications.
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
            # AuthenticationMiddleware may reject an inactive user
            # while stale auth keys remain in the session. Do not
            # keep such an authenticated-looking session around.
            if SESSION_KEY in session:
                session.flush()

            response = self.get_response(request)

            # A successful login can happen inside the view, after
            # this middleware has already observed AnonymousUser.
            # Initialize the fixed security timestamps on that same
            # request so absolute lifetime starts at login time,
            # not at the next page request.
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

            return response

        role, policy = _policy_for(user)

        if policy is None:
            # Unknown or invalid authentication role/policy:
            # fail closed.
            logout(request)
            return self.get_response(request)

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
            # Legacy sessions created before deployment of this
            # middleware are upgraded on their first request.
            _initialize_session(
                session,
                role=role,
                now=now,
            )

            return self.get_response(request)

        if not all(present):
            # Partial/corrupt security metadata is not trusted.
            logout(request)
            return self.get_response(request)

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
            return self.get_response(request)

        (
            idle_seconds,
            absolute_seconds,
        ) = policy

        if (
            now - started_at >= absolute_seconds
            or now - last_seen_at >= idle_seconds
        ):
            logout(request)
            return self.get_response(request)

        touch_seconds = _positive_int(
            getattr(
                settings,
                "AUTH_SESSION_ACTIVITY_TOUCH_SECONDS",
                60,
            )
        )

        if touch_seconds is None:
            logout(request)
            return self.get_response(request)

        # Avoid a DB-backed session write on every single HTTP
        # request while still tracking meaningful activity.
        if (
            now - last_seen_at
            >= touch_seconds
        ):
            session[
                SESSION_LAST_SEEN_AT_KEY
            ] = now

        return self.get_response(request)
