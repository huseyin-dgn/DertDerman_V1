from types import SimpleNamespace
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from notifications.email_service import EmailDeliveryError

from accounts.email_change import (
    make_email_change_token,
    send_email_change_verification,
)
from accounts.models import User


class EmailChangeTests(TestCase):
    password = "River!8327Stone"

    def create_user(self, **overrides):
        data = {
            "username": "email-user",
            "email": "old@example.com",
            "password": self.password,
            "user_type": User.UserType.USER,
            "is_active": True,
            "is_verified": True,
        }
        data.update(overrides)
        return User.objects.create_user(**data)

    def login(self, user):
        self.client.force_login(user)

    def confirm_url(self, token):
        return reverse(
            "accounts:email_change_confirm",
            kwargs={"token": token},
        )

    def test_request_requires_authenticated_user(self):
        response = self.client.get(
            reverse("accounts:email_change")
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse("accounts:login"),
            response["Location"],
        )

    def test_wrong_current_password_does_not_reveal_email_availability(self):
        user = self.create_user()
        self.create_user(
            username="other-user",
            email="used@example.com",
        )
        self.login(user)

        response = self.client.post(
            reverse("accounts:email_change"),
            {
                "current_password": "wrong-password",
                "new_email": "used@example.com",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Mevcut şifreniz doğru değil.",
        )
        self.assertNotContains(
            response,
            "başka bir hesapta kullanılıyor",
        )

    @patch("accounts.email_change_views.send_email_change_verification")
    def test_valid_request_sends_verification_and_keeps_old_email(
        self,
        send_verification,
    ):
        user = self.create_user()
        self.login(user)
        send_verification.return_value = SimpleNamespace(status="sent")

        response = self.client.post(
            reverse("accounts:email_change"),
            {
                "current_password": self.password,
                "new_email": "new-address@example.com",
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:email_change_pending"),
        )
        user.refresh_from_db()
        self.assertEqual(user.email, "old@example.com")
        send_verification.assert_called_once_with(
            user,
            "new-address@example.com",
        )

    def test_same_and_used_email_are_rejected_after_password_check(self):
        user = self.create_user()
        self.create_user(
            username="other-user",
            email="used@example.com",
        )
        self.login(user)

        same = self.client.post(
            reverse("accounts:email_change"),
            {
                "current_password": self.password,
                "new_email": "OLD@example.com",
            },
        )
        self.assertContains(
            same,
            "mevcut adresinizden farklı",
        )

        used = self.client.post(
            reverse("accounts:email_change"),
            {
                "current_password": self.password,
                "new_email": "used@example.com",
            },
        )
        self.assertContains(
            used,
            "başka bir hesapta kullanılıyor",
        )

    @patch("accounts.email_change_views.send_email_change_verification")
    def test_provider_failure_does_not_change_email(
        self,
        send_verification,
    ):
        user = self.create_user()
        self.login(user)
        send_verification.side_effect = EmailDeliveryError("provider detail")

        response = self.client.post(
            reverse("accounts:email_change"),
            {
                "current_password": self.password,
                "new_email": "new-address@example.com",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Doğrulama e-postası şu anda gönderilemedi",
        )
        self.assertNotContains(response, "provider detail")
        user.refresh_from_db()
        self.assertEqual(user.email, "old@example.com")

    @override_settings(
        SITE_BASE_URL="https://dertderman.com",
        SUPPORT_EMAIL="destek@dertderman.com",
        SUPPORT_PHONE="+90 850 532 2206",
        SUPPORT_HOURS="Hafta içi 09:00 - 18:00",
    )
    @patch("accounts.email_change.send_email")
    def test_mail_uses_central_service_and_targets_new_email(
        self,
        send_email,
    ):
        user = self.create_user()
        send_email.return_value = SimpleNamespace(status="sent")

        send_email_change_verification(
            user,
            "new-address@example.com",
        )

        kwargs = send_email.call_args.kwargs
        self.assertEqual(
            kwargs["recipient_email"],
            "new-address@example.com",
        )
        self.assertIn(
            "https://dertderman.com/hesap/eposta-degistir/onayla/",
            kwargs["html_body"],
        )
        self.assertIn(
            "https://dertderman.com/hesap/eposta-degistir/onayla/",
            kwargs["text_body"],
        )
        self.assertNotIn(
            "new-address@example.com",
            kwargs["event_key"],
        )

    def test_get_confirmation_does_not_change_email(self):
        user = self.create_user()
        self.login(user)
        token = make_email_change_token(
            user,
            "new-address@example.com",
        )

        response = self.client.get(
            self.confirm_url(token)
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "new-address@example.com",
        )
        user.refresh_from_db()
        self.assertEqual(user.email, "old@example.com")

    def test_post_changes_email_and_token_becomes_single_use(self):
        user = self.create_user()
        self.login(user)
        token = make_email_change_token(
            user,
            "new-address@example.com",
        )
        url = self.confirm_url(token)

        response = self.client.post(url)

        self.assertRedirects(
            response,
            reverse("accounts:email_change_complete"),
        )

        user.refresh_from_db()
        self.assertEqual(
            user.email,
            "new-address@example.com",
        )
        self.assertTrue(user.is_verified)

        reused = self.client.get(url)
        self.assertEqual(reused.status_code, 400)

    def test_different_logged_in_user_cannot_confirm_token(self):
        user = self.create_user()
        other = self.create_user(
            username="second-user",
            email="second@example.com",
        )
        token = make_email_change_token(
            user,
            "new-address@example.com",
        )
        self.login(other)

        response = self.client.get(
            self.confirm_url(token)
        )

        self.assertEqual(response.status_code, 403)
        user.refresh_from_db()
        self.assertEqual(user.email, "old@example.com")

    def test_tampered_token_is_rejected(self):
        user = self.create_user()
        self.login(user)
        token = make_email_change_token(
            user,
            "new-address@example.com",
        )

        response = self.client.get(
            self.confirm_url(f"{token}x")
        )

        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertEqual(user.email, "old@example.com")

    @override_settings(EMAIL_CHANGE_TIMEOUT=-1)
    def test_expired_token_is_rejected(self):
        user = self.create_user()
        self.login(user)
        token = make_email_change_token(
            user,
            "new-address@example.com",
        )

        response = self.client.get(
            self.confirm_url(token)
        )

        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertEqual(user.email, "old@example.com")

    def test_request_and_confirmation_post_require_csrf(self):
        user = self.create_user()
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)

        request_response = client.post(
            reverse("accounts:email_change"),
            {
                "current_password": self.password,
                "new_email": "new-address@example.com",
            },
        )
        self.assertEqual(request_response.status_code, 403)

        token = make_email_change_token(
            user,
            "new-address@example.com",
        )
        confirm_response = client.post(
            self.confirm_url(token)
        )
        self.assertEqual(confirm_response.status_code, 403)

        user.refresh_from_db()
        self.assertEqual(user.email, "old@example.com")

    def test_profile_edit_cannot_change_email_directly(self):
        user = self.create_user(
            first_name="Old",
            last_name="Name",
        )
        self.login(user)

        response = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "first_name": "New",
                "last_name": "Name",
                "phone": "5551112233",
                "selected_avatar": "",
                "email": "bypass@example.com",
            },
        )

        self.assertRedirects(
            response,
            reverse("accounts:profile"),
        )
        user.refresh_from_db()
        self.assertEqual(user.email, "old@example.com")
        self.assertEqual(user.first_name, "New")
