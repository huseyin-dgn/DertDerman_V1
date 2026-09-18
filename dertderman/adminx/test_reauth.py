from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from core.session_security import (
    SESSION_REAUTH_AT_KEY,
)


@override_settings(
    AUTH_SESSION_SECURITY_ENABLED=True,
    RATE_LIMIT_ENABLED=True,
)
class AdminReauthenticationTests(TestCase):
    password = "AdminReauthPassword2026!"

    def setUp(self):
        cache.clear()

        self.admin = (
            get_user_model()
            .objects
            .create_user(
                username="reauth-admin",
                email="reauth-admin@example.com",
                user_type="ADMIN",
                password=self.password,
            )
        )

    def _login(self):
        response = self.client.post(
            reverse("adminx:login"),
            {
                "username":
                    self.admin.username,
                "password":
                    self.password,
            },
        )

        self.assertRedirects(
            response,
            reverse("adminx:home"),
        )

    def test_admin_login_marks_recent_authentication(self):
        self._login()

        self.assertIn(
            SESSION_REAUTH_AT_KEY,
            self.client.session,
        )

    def test_successful_reauthentication_rotates_session_key(self):
        self._login()

        old_key = (
            self.client.session.session_key
        )

        response = self.client.post(
            reverse("adminx:reauth"),
            {
                "password":
                    self.password,
                "next":
                    reverse(
                        "adminx:blog_list"
                    ),
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "adminx:blog_list"
            ),
        )

        self.assertNotEqual(
            self.client.session.session_key,
            old_key,
        )

        self.assertIn(
            SESSION_REAUTH_AT_KEY,
            self.client.session,
        )

    def test_wrong_password_does_not_refresh_authentication(self):
        self._login()

        session = self.client.session
        session.pop(
            SESSION_REAUTH_AT_KEY,
            None,
        )
        session.save()

        response = self.client.post(
            reverse("adminx:reauth"),
            {
                "password":
                    "wrong-password",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertNotIn(
            SESSION_REAUTH_AT_KEY,
            self.client.session,
        )

    def test_external_next_is_rejected(self):
        self._login()

        response = self.client.post(
            reverse("adminx:reauth"),
            {
                "password":
                    self.password,
                "next":
                    "https://example.com/steal",
            },
        )

        self.assertRedirects(
            response,
            reverse("adminx:home"),
        )

    def test_non_admin_cannot_use_admin_reauthentication(self):
        company_user = (
            get_user_model()
            .objects
            .create_user(
                username="reauth-company",
                email="reauth-company@example.com",
                user_type="COMPANY",
                password=self.password,
            )
        )

        self.client.force_login(
            company_user
        )

        response = self.client.get(
            reverse("adminx:reauth")
        )

        self.assertEqual(
            response.status_code,
            403,
        )
