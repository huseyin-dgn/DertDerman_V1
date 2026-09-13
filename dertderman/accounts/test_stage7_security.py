from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import User


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

    def test_user_login_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            reverse("accounts:login"),
            {"username": "any", "password": "any"},
        )
        self.assertEqual(response.status_code, 403)
