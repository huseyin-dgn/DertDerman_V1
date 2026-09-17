from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .auth_views import COMPANY_LOGIN_POLICY


@override_settings(RATE_LIMIT_ENABLED=True)
class CompanyStage7SecurityTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_company_login_blocks_after_repeated_failed_attempts(self):
        url = reverse("company_auth:login")
        for _ in range(5):
            response = self.client.post(
                url,
                {"email": "missing@example.com", "password": "WrongPass2026!"},
                REMOTE_ADDR="127.0.0.40",
            )
            self.assertEqual(response.status_code, 200)
        blocked = self.client.post(
            url,
            {"email": "missing@example.com", "password": "WrongPass2026!"},
            REMOTE_ADDR="127.0.0.40",
        )
        self.assertEqual(blocked.status_code, 429)

    def test_company_login_account_limit_survives_ip_rotation(self):
        url = reverse("company_auth:login")

        for index in range(
            COMPANY_LOGIN_POLICY.identity_limit
        ):
            response = self.client.post(
                url,
                {
                    "email":
                        "rotation-target@example.com",
                    "password":
                        "WrongPass2026!",
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
                "email":
                    "rotation-target@example.com",
                "password":
                    "WrongPass2026!",
            },
            REMOTE_ADDR="203.0.113.201",
        )

        self.assertEqual(
            blocked.status_code,
            429,
        )
        self.assertIn(
            "Retry-After",
            blocked.headers,
        )

    def test_company_registration_is_rate_limited_by_ip(self):
        url = reverse("company_auth:register")
        for _ in range(10):
            self.assertEqual(self.client.post(url, {}, REMOTE_ADDR="127.0.0.50").status_code, 200)
        self.assertEqual(self.client.post(url, {}, REMOTE_ADDR="127.0.0.50").status_code, 429)

    def test_company_login_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            reverse("company_auth:login"),
            {"email": "missing@example.com", "password": "WrongPass2026!"},
        )
        self.assertEqual(response.status_code, 403)
