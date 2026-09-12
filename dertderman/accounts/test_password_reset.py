from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.tokens import (
    default_token_generator,
)
from django.test import (
    Client,
    TestCase,
    override_settings,
)
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import (
    urlsafe_base64_encode,
)

from notifications.email_service import (
    EmailDeliveryError,
)

from accounts.models import User
from accounts.password_reset import (
    send_password_reset_email,
)
from accounts.password_reset_views import (
    GENERIC_RESET_MESSAGE,
)


class PasswordResetTests(TestCase):
    password = "Granite!9284Ocean"

    def create_user(
        self,
        **overrides,
    ):
        data = {
            "username": "reset-user",
            "email": "reset-user@example.com",
            "password": self.password,
            "user_type": User.UserType.USER,
            "is_active": True,
            "is_verified": True,
        }
        data.update(overrides)
        return User.objects.create_user(
            **data
        )

    def reset_route(
        self,
        user,
        token=None,
    ):
        uidb64 = urlsafe_base64_encode(
            force_bytes(user.pk)
        )
        token = (
            token
            or default_token_generator
            .make_token(user)
        )
        return reverse(
            "accounts:password_reset_confirm",
            kwargs={
                "uidb64": uidb64,
                "token": token,
            },
        )

    @patch(
        "accounts.password_reset.send_email"
    )
    def test_known_verified_user_gets_reset_email(
        self,
        send_email,
    ):
        send_email.return_value = (
            SimpleNamespace(status="sent")
        )
        user = self.create_user()

        response = self.client.post(
            reverse(
                "accounts:password_reset"
            ),
            {
                "email": user.email,
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "accounts:password_reset_done"
            ),
        )
        self.assertNotIn(
            "_auth_user_id",
            self.client.session,
        )
        send_email.assert_called_once()

    @patch(
        "accounts.password_reset.send_email"
    )
    def test_unknown_email_has_same_public_result(
        self,
        send_email,
    ):
        response = self.client.post(
            reverse(
                "accounts:password_reset"
            ),
            {
                "email": (
                    "missing@example.com"
                ),
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "accounts:password_reset_done"
            ),
        )
        send_email.assert_not_called()

        done = self.client.get(
            reverse(
                "accounts:password_reset_done"
            )
        )
        self.assertContains(
            done,
            GENERIC_RESET_MESSAGE,
        )

    @patch(
        "accounts.password_reset.send_email"
    )
    def test_ineligible_accounts_do_not_reveal_state(
        self,
        send_email,
    ):
        cases = (
            {
                "username": "unverified",
                "email": "unverified@example.com",
                "is_verified": False,
            },
            {
                "username": "inactive",
                "email": "inactive@example.com",
                "is_active": False,
            },
            {
                "username": "company-reset",
                "email": "company-reset@example.com",
                "user_type": User.UserType.COMPANY,
            },
            {
                "username": "admin-reset",
                "email": "admin-reset@example.com",
                "user_type": User.UserType.ADMIN,
            },
        )

        for case in cases:
            with self.subTest(
                email=case["email"]
            ):
                user = self.create_user(
                    **case
                )

                response = (
                    self.client.post(
                        reverse(
                            "accounts:password_reset"
                        ),
                        {
                            "email": user.email,
                        },
                    )
                )

                self.assertRedirects(
                    response,
                    reverse(
                        "accounts:password_reset_done"
                    ),
                )

        send_email.assert_not_called()

    @patch(
        "accounts.password_reset.send_email"
    )
    def test_provider_failure_still_returns_generic_result(
        self,
        send_email,
    ):
        user = self.create_user()
        send_email.side_effect = (
            EmailDeliveryError(
                "provider detail"
            )
        )

        response = self.client.post(
            reverse(
                "accounts:password_reset"
            ),
            {
                "email": user.email,
            },
            follow=True,
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertContains(
            response,
            GENERIC_RESET_MESSAGE,
        )
        self.assertNotContains(
            response,
            "provider detail",
        )

    @override_settings(
        SITE_BASE_URL=(
            "https://dertderman.com"
        ),
        SUPPORT_EMAIL=(
            "destek@dertderman.com"
        ),
        SUPPORT_PHONE=(
            "+90 850 532 2206"
        ),
        SUPPORT_HOURS=(
            "Hafta içi 09:00 - 18:00"
        ),
    )
    @patch(
        "accounts.password_reset.send_email"
    )
    def test_email_uses_central_service_html_and_text(
        self,
        send_email,
    ):
        user = self.create_user()
        send_email.return_value = (
            SimpleNamespace(status="sent")
        )

        send_password_reset_email(
            user
        )

        kwargs = (
            send_email.call_args.kwargs
        )

        self.assertEqual(
            kwargs["recipient_email"],
            user.email,
        )
        self.assertIn(
            (
                "https://dertderman.com/"
                "hesap/sifre-sifirla/"
            ),
            kwargs["html_body"],
        )
        self.assertIn(
            (
                "https://dertderman.com/"
                "hesap/sifre-sifirla/"
            ),
            kwargs["text_body"],
        )
        self.assertIn(
            "DertDerman",
            kwargs["html_body"],
        )
        self.assertIn(
            "DertDerman",
            kwargs["text_body"],
        )
        self.assertNotIn(
            user.email,
            kwargs["event_key"],
        )

    def test_valid_link_get_does_not_change_password(
        self,
    ):
        user = self.create_user()
        original_hash = user.password

        response = self.client.get(
            self.reset_route(user)
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        user.refresh_from_db()
        self.assertEqual(
            user.password,
            original_hash,
        )

        form_page = self.client.get(
            response["Location"]
        )
        self.assertEqual(
            form_page.status_code,
            200,
        )
        self.assertTrue(
            form_page.context[
                "validlink"
            ]
        )

    def test_post_changes_password_and_token_becomes_invalid(
        self,
    ):
        user = self.create_user()
        original_route = (
            self.reset_route(user)
        )

        first = self.client.get(
            original_route
        )
        self.assertEqual(
            first.status_code,
            302,
        )

        new_password = (
            "Cedar!4719Galaxy"
        )

        response = self.client.post(
            first["Location"],
            {
                "new_password1": (
                    new_password
                ),
                "new_password2": (
                    new_password
                ),
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "accounts:password_reset_complete"
            ),
        )

        user.refresh_from_db()
        self.assertTrue(
            user.check_password(
                new_password
            )
        )
        self.assertFalse(
            user.check_password(
                self.password
            )
        )
        self.assertNotIn(
            "_auth_user_id",
            self.client.session,
        )

        reused = self.client.get(
            original_route
        )
        self.assertEqual(
            reused.status_code,
            200,
        )
        self.assertFalse(
            reused.context["validlink"]
        )

    def test_tampered_token_never_changes_password(
        self,
    ):
        user = self.create_user()
        original_hash = user.password
        good = (
            default_token_generator
            .make_token(user)
        )
        tampered = f"{good}x"

        response = self.client.get(
            self.reset_route(
                user,
                token=tampered,
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertFalse(
            response.context["validlink"]
        )

        user.refresh_from_db()
        self.assertEqual(
            user.password,
            original_hash,
        )

    @override_settings(
        PASSWORD_RESET_TIMEOUT=-1
    )
    def test_expired_token_is_rejected(
        self,
    ):
        user = self.create_user()
        route = self.reset_route(user)

        response = self.client.get(
            route
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertFalse(
            response.context["validlink"]
        )

    def test_request_and_password_update_require_csrf(
        self,
    ):
        user = self.create_user()
        client = Client(
            enforce_csrf_checks=True
        )

        request_response = (
            client.post(
                reverse(
                    "accounts:password_reset"
                ),
                {
                    "email": user.email,
                },
            )
        )
        self.assertEqual(
            request_response.status_code,
            403,
        )

        original_route = (
            self.reset_route(user)
        )
        first = client.get(
            original_route
        )
        self.assertEqual(
            first.status_code,
            302,
        )

        update_response = (
            client.post(
                first["Location"],
                {
                    "new_password1": (
                        "Quartz!6591Forest"
                    ),
                    "new_password2": (
                        "Quartz!6591Forest"
                    ),
                },
            )
        )
        self.assertEqual(
            update_response.status_code,
            403,
        )

        user.refresh_from_db()
        self.assertTrue(
            user.check_password(
                self.password
            )
        )

    def test_login_page_links_to_password_reset(
        self,
    ):
        response = self.client.get(
            reverse("accounts:login")
        )

        self.assertContains(
            response,
            reverse(
                "accounts:password_reset"
            ),
        )
        self.assertContains(
            response,
            "Şifremi unuttum",
        )
