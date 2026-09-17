from unittest.mock import patch

from django.contrib.auth import SESSION_KEY, login
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import (
    RequestFactory,
    TestCase,
    override_settings,
)

from accounts.models import User

from .session_security import (
    SESSION_LAST_SEEN_AT_KEY,
    SESSION_ROLE_KEY,
    SESSION_STARTED_AT_KEY,
    SessionSecurityMiddleware,
)


TEST_POLICIES = {
    "USER": {
        "idle_seconds": 100,
        "absolute_seconds": 1000,
    },
    "COMPANY": {
        "idle_seconds": 80,
        "absolute_seconds": 800,
    },
    "ADMIN": {
        "idle_seconds": 30,
        "absolute_seconds": 200,
    },
}


@override_settings(
    AUTH_SESSION_SECURITY_ENABLED=True,
    AUTH_SESSION_ACTIVITY_TOUCH_SECONDS=10,
    AUTH_SESSION_SECURITY_POLICIES=TEST_POLICIES,
)
class SessionSecurityMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        self.user = User.objects.create_user(
            username="session-user",
            email="session-user@example.com",
            password="SessionSecurityPassword2026!",
            user_type=User.UserType.USER,
            is_verified=True,
        )

    def _request(self, user=None):
        request = self.factory.get("/probe/")

        middleware = SessionMiddleware(
            lambda req: HttpResponse()
        )
        middleware.process_request(request)
        request.session.save()

        request.user = (
            user
            if user is not None
            else self.user
        )

        return request

    def _run(self, request, now):
        middleware = SessionSecurityMiddleware(
            lambda req: HttpResponse(
                "authenticated"
                if req.user.is_authenticated
                else "anonymous"
            )
        )

        with patch(
            "core.session_security.time.time",
            return_value=now,
        ):
            return middleware(request)

    def _seed(
        self,
        request,
        *,
        started,
        last_seen,
        role="USER",
    ):
        request.session[
            SESSION_STARTED_AT_KEY
        ] = started
        request.session[
            SESSION_LAST_SEEN_AT_KEY
        ] = last_seen
        request.session[
            SESSION_ROLE_KEY
        ] = role

    def test_legacy_authenticated_session_is_initialized(self):
        request = self._request()

        response = self._run(
            request,
            1000,
        )

        self.assertEqual(
            response.content,
            b"authenticated",
        )
        self.assertEqual(
            request.session[
                SESSION_STARTED_AT_KEY
            ],
            1000,
        )
        self.assertEqual(
            request.session[
                SESSION_LAST_SEEN_AT_KEY
            ],
            1000,
        )
        self.assertEqual(
            request.session[
                SESSION_ROLE_KEY
            ],
            "USER",
        )

    def test_fresh_login_initializes_security_metadata_immediately(self):
        request = self._request(
            AnonymousUser()
        )

        def login_view(req):
            login(
                req,
                self.user,
                backend=(
                    "django.contrib.auth.backends."
                    "ModelBackend"
                ),
            )
            return HttpResponse("logged-in")

        middleware = SessionSecurityMiddleware(
            login_view
        )

        with patch(
            "core.session_security.time.time",
            return_value=1000,
        ):
            response = middleware(request)

        self.assertEqual(
            response.content,
            b"logged-in",
        )
        self.assertTrue(
            request.user.is_authenticated
        )
        self.assertEqual(
            request.session[
                SESSION_STARTED_AT_KEY
            ],
            1000,
        )
        self.assertEqual(
            request.session[
                SESSION_LAST_SEEN_AT_KEY
            ],
            1000,
        )
        self.assertEqual(
            request.session[
                SESSION_ROLE_KEY
            ],
            "USER",
        )

    def test_idle_timeout_logs_user_out(self):
        request = self._request()

        self._seed(
            request,
            started=1000,
            last_seen=1000,
        )

        response = self._run(
            request,
            1100,
        )

        self.assertEqual(
            response.content,
            b"anonymous",
        )
        self.assertFalse(
            request.user.is_authenticated
        )

    def test_absolute_timeout_logs_user_out_even_when_recently_active(self):
        request = self._request()

        self._seed(
            request,
            started=1000,
            last_seen=1995,
        )

        response = self._run(
            request,
            2000,
        )

        self.assertEqual(
            response.content,
            b"anonymous",
        )
        self.assertFalse(
            request.user.is_authenticated
        )

    def test_activity_touch_preserves_absolute_start(self):
        request = self._request()

        self._seed(
            request,
            started=1000,
            last_seen=1000,
        )

        response = self._run(
            request,
            1011,
        )

        self.assertEqual(
            response.content,
            b"authenticated",
        )
        self.assertEqual(
            request.session[
                SESSION_STARTED_AT_KEY
            ],
            1000,
        )
        self.assertEqual(
            request.session[
                SESSION_LAST_SEEN_AT_KEY
            ],
            1011,
        )

    def test_role_change_invalidates_existing_session(self):
        request = self._request()

        self._seed(
            request,
            started=1000,
            last_seen=1000,
            role="COMPANY",
        )

        response = self._run(
            request,
            1010,
        )

        self.assertEqual(
            response.content,
            b"anonymous",
        )
        self.assertFalse(
            request.user.is_authenticated
        )

    def test_partial_security_metadata_fails_closed(self):
        request = self._request()

        request.session[
            SESSION_STARTED_AT_KEY
        ] = 1000

        response = self._run(
            request,
            1010,
        )

        self.assertEqual(
            response.content,
            b"anonymous",
        )
        self.assertFalse(
            request.user.is_authenticated
        )

    def test_stale_auth_keys_are_flushed_for_anonymous_user(self):
        request = self._request(
            AnonymousUser()
        )

        request.session[
            SESSION_KEY
        ] = str(self.user.pk)

        self._run(
            request,
            1000,
        )

        self.assertNotIn(
            SESSION_KEY,
            request.session,
        )
