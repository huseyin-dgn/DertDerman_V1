from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.rate_limit import (
    AuthRateLimitPolicy,
    consume_auth_failure,
)

from .forms import UserAuthenticationForm
from .models import User
from .views import USER_LOGIN_POLICY


@override_settings(RATE_LIMIT_ENABLED=True)
class AccountStage7SecurityTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_user_login_blocks_after_repeated_failed_attempts(self):
        url = reverse("accounts:login")
        for _ in range(5):
            response = self.client.post(
                url,
                {"username": "missing-user", "password": "WrongPass2026!"},
                REMOTE_ADDR="127.0.0.10",
            )
            self.assertEqual(response.status_code, 200)
        blocked = self.client.post(
            url,
            {"username": "missing-user", "password": "WrongPass2026!"},
            REMOTE_ADDR="127.0.0.10",
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)

    def test_user_login_account_limit_survives_ip_rotation(self):
        url = reverse("accounts:login")

        for index in range(
            USER_LOGIN_POLICY.identity_limit
        ):
            response = self.client.post(
                url,
                {
                    "username": "rotation-target",
                    "password": "WrongPass2026!",
                },
                REMOTE_ADDR=(
                    f"198.51.100.{index + 1}"
                ),
            )
            self.assertEqual(
                response.status_code,
                200,
            )

        blocked = self.client.post(
            url,
            {
                "username": "rotation-target",
                "password": "WrongPass2026!",
            },
            REMOTE_ADDR="203.0.113.200",
        )

        self.assertEqual(
            blocked.status_code,
            429,
        )
        self.assertIn(
            "Retry-After",
            blocked.headers,
        )

    @patch("accounts.password_reset_views.request_password_reset")
    def test_password_reset_limit_keeps_generic_redirect(self, request_password_reset):
        url = reverse("accounts:password_reset")
        done_url = reverse("accounts:password_reset_done")
        for _ in range(6):
            response = self.client.post(
                url,
                {"email": "target@example.com"},
                REMOTE_ADDR="127.0.0.20",
            )
            self.assertRedirects(response, done_url, fetch_redirect_response=False)
        self.assertEqual(request_password_reset.call_count, 5)

    @patch("accounts.email_change_views.send_email_change_verification")
    def test_email_change_is_rate_limited_per_user(self, send_verification):
        send_verification.return_value = SimpleNamespace(status="sent")
        user = User.objects.create_user(
            username="stage7-user",
            email="stage7@example.com",
            password="StrongPass2026!",
            user_type=User.UserType.USER,
            is_verified=True,
        )
        self.client.force_login(user)
        url = reverse("accounts:email_change")
        for index in range(3):
            response = self.client.post(
                url,
                {"current_password": "StrongPass2026!", "new_email": f"new-{index}@example.com"},
            )
            self.assertEqual(response.status_code, 302)
        blocked = self.client.post(
            url,
            {"current_password": "StrongPass2026!", "new_email": "blocked@example.com"},
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(send_verification.call_count, 3)

    def test_user_registration_is_rate_limited_by_ip(self):
        url = reverse("accounts:register")
        for _ in range(10):
            self.assertEqual(self.client.post(url, {}, REMOTE_ADDR="127.0.0.30").status_code, 200)
        self.assertEqual(self.client.post(url, {}, REMOTE_ADDR="127.0.0.30").status_code, 429)

    def test_throttled_user_login_never_runs_credential_validation(self):
        url = reverse("accounts:login")
        ip_address = "192.0.2.81"
        identity = "already-throttled-user"

        # Fill the IP+identity bucket entirely with failures.
        for _ in range(
            USER_LOGIN_POLICY.pair_limit
        ):
            decision = consume_auth_failure(
                scope="user-login",
                ip_address=ip_address,
                identity=identity,
                policy=USER_LOGIN_POLICY,
            )
            self.assertTrue(decision.allowed)

        # If UserAuthenticationForm.clean() executes, this test must
        # fail immediately. A throttled request must be rejected
        # before credential verification/password hashing begins.
        with patch.object(
            UserAuthenticationForm,
            "clean",
            side_effect=AssertionError(
                "credential validation must not run "
                "after authentication throttling"
            ),
        ) as clean_mock:
            response = self.client.post(
                url,
                {
                    "username": identity,
                    "password": "NeverValidateThisPassword2026!",
                },
                REMOTE_ADDR=ip_address,
            )

        self.assertEqual(
            response.status_code,
            429,
        )
        self.assertIn(
            "Retry-After",
            response.headers,
        )
        self.assertNotIn(
            "_auth_user_id",
            self.client.session,
        )
        clean_mock.assert_not_called()

    def test_successful_logins_do_not_consume_failure_ip_quota(self):
        password = "SuccessfulLoginQuota2026!"

        user = User.objects.create_user(
            username="successful-login-quota-user",
            email="successful-login-quota@example.com",
            password=password,
            user_type=User.UserType.USER,
            is_verified=True,
        )

        # Keep the integration test fast while preserving the exact
        # production control flow. If successful requests consumed
        # the IP failure bucket, the fourth login would be blocked.
        policy = AuthRateLimitPolicy(
            pair_limit=2,
            pair_window_seconds=900,
            identity_limit=3,
            identity_window_seconds=3600,
            ip_limit=3,
            ip_window_seconds=900,
        )

        url = reverse("accounts:login")
        ip_address = "192.0.2.82"

        with patch(
            "accounts.views.USER_LOGIN_POLICY",
            policy,
        ):
            for attempt in range(
                policy.ip_limit + 2
            ):
                with self.subTest(
                    attempt=attempt + 1
                ):
                    client = Client()

                    response = client.post(
                        url,
                        {
                            "username": user.username,
                            "password": password,
                        },
                        REMOTE_ADDR=ip_address,
                    )

                    self.assertEqual(
                        response.status_code,
                        302,
                    )
                    self.assertIn(
                        "_auth_user_id",
                        client.session,
                    )
                    self.assertEqual(
                        int(
                            client.session[
                                "_auth_user_id"
                            ]
                        ),
                        user.pk,
                    )

    def test_user_login_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            reverse("accounts:login"),
            {"username": "any", "password": "any"},
        )
        self.assertEqual(response.status_code, 403)
