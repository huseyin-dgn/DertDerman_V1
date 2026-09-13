from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse


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
