from types import SimpleNamespace
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.email_verification import (
    make_email_verification_token,
    resolve_email_verification_token,
    send_verification_email,
)
from accounts.forms import UNVERIFIED_LOGIN_ERROR
from accounts.models import User


class EmailVerificationTests(TestCase):
    password = "StrongRiver#9284Moon"

    def create_user(self, **overrides):
        data = {
            "username": "verify-user",
            "email": "verify-user@example.com",
            "password": self.password,
            "user_type": User.UserType.USER,
            "is_verified": False,
        }
        data.update(overrides)
        return User.objects.create_user(**data)

    @patch("accounts.views.send_verification_email")
    def test_registration_creates_unverified_user_without_login(self, send_verification):
        send_verification.return_value = SimpleNamespace(status="sent")

        response = self.client.post(
            reverse("accounts:register"),
            {
                "username": "new-verification-user",
                "email": "new-verification-user@example.com",
                "password1": self.password,
                "password2": self.password,
                "selected_avatar": "avatar-1",
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:email_verification_pending"),
        )
        self.assertNotIn("_auth_user_id", self.client.session)

        user = User.objects.get(username="new-verification-user")
        self.assertFalse(user.is_verified)
        send_verification.assert_called_once_with(user)

    def test_unverified_user_cannot_login_even_with_correct_password(self):
        user = self.create_user()

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": user.username,
                "password": self.password,
            },
        )

        self.assertContains(response, UNVERIFIED_LOGIN_ERROR)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_verified_user_can_login(self):
        user = self.create_user(is_verified=True)

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": user.username,
                "password": self.password,
            },
        )

        self.assertRedirects(response, reverse("dashboard:home"))

    def test_get_confirmation_page_never_verifies_account(self):
        user = self.create_user()
        token = make_email_verification_token(user)

        response = self.client.get(
            reverse(
                "accounts:email_verification_confirm",
                kwargs={"token": token},
            )
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.is_verified)
        self.assertContains(response, "E-postamı Doğrula")

    def test_post_confirmation_verifies_account(self):
        user = self.create_user()
        token = make_email_verification_token(user)
        route = reverse(
            "accounts:email_verification_confirm",
            kwargs={"token": token},
        )

        response = self.client.post(route)

        self.assertRedirects(response, reverse("accounts:login"))
        user.refresh_from_db()
        self.assertTrue(user.is_verified)

    def test_token_is_single_use(self):
        user = self.create_user()
        token = make_email_verification_token(user)
        route = reverse(
            "accounts:email_verification_confirm",
            kwargs={"token": token},
        )

        self.assertEqual(self.client.post(route).status_code, 302)
        self.assertEqual(self.client.get(route).status_code, 400)
        self.assertIsNone(resolve_email_verification_token(token))

    def test_tampered_token_is_rejected(self):
        user = self.create_user()
        token = make_email_verification_token(user)
        tampered = f"{token}x"

        response = self.client.get(
            reverse(
                "accounts:email_verification_confirm",
                kwargs={"token": tampered},
            )
        )

        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertFalse(user.is_verified)

    @override_settings(EMAIL_VERIFICATION_TIMEOUT=-1)
    def test_expired_token_is_rejected(self):
        user = self.create_user()
        token = make_email_verification_token(user)
        self.assertIsNone(resolve_email_verification_token(token))

    def test_verification_post_requires_csrf(self):
        user = self.create_user()
        token = make_email_verification_token(user)
        route = reverse(
            "accounts:email_verification_confirm",
            kwargs={"token": token},
        )

        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(route).status_code, 200)
        self.assertEqual(client.post(route).status_code, 403)

        user.refresh_from_db()
        self.assertFalse(user.is_verified)

    @override_settings(
        SITE_BASE_URL="https://dertderman.com",
        SUPPORT_EMAIL="destek@dertderman.com",
        SUPPORT_PHONE="+90 850 532 2206",
        SUPPORT_HOURS="Hafta içi 09:00 - 18:00",
    )
    @patch("accounts.email_verification.send_email")
    def test_email_uses_fixed_site_base_url_html_and_text(self, send_email):
        user = self.create_user()
        send_email.return_value = SimpleNamespace(status="sent")

        send_verification_email(user)

        kwargs = send_email.call_args.kwargs
        self.assertEqual(kwargs["recipient_email"], user.email)
        self.assertIn("https://dertderman.com/hesap/eposta-dogrula/", kwargs["html_body"])
        self.assertIn("https://dertderman.com/hesap/eposta-dogrula/", kwargs["text_body"])
        self.assertIn("DertDerman", kwargs["html_body"])
        self.assertIn("DertDerman", kwargs["text_body"])
        self.assertNotIn(user.email, kwargs["event_key"])
