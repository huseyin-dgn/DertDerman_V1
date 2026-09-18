from django.contrib.sessions.models import Session
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

from accounts.email_change import (
    make_email_change_token,
)
from accounts.models import User
from accounts.password_reset import (
    password_reset_token_generator,
)


@override_settings(
    AUTH_SESSION_SECURITY_ENABLED=True,
)
class CredentialSessionRevocationTests(TestCase):
    password = "Granite!9284Ocean"

    def create_user(self):
        return User.objects.create_user(
            username="credential-session-user",
            email="credential-session@example.com",
            password=self.password,
            user_type=User.UserType.USER,
            is_active=True,
            is_verified=True,
        )

    def activate_authenticated_session(
        self,
        client,
    ):
        """
        force_login() test client shortcut'u gerçek HTTP login
        middleware zincirini çalıştırmaz.

        İlk authenticated request registry kaydını oluşturur ve
        production session davranışını simüle eder.
        """
        response = client.get(
            reverse("accounts:profile")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        return client.session.session_key

    def assert_login_redirect(self, response):
        self.assertEqual(
            response.status_code,
            302,
        )
        self.assertIn(
            reverse("accounts:login"),
            response["Location"],
        )

    def test_password_change_keeps_current_session_and_revokes_other_devices(self):
        user = self.create_user()

        primary = Client()
        secondary = Client()

        primary.force_login(user)
        secondary.force_login(user)

        old_primary_key = (
            self.activate_authenticated_session(
                primary
            )
        )
        secondary_key = (
            self.activate_authenticated_session(
                secondary
            )
        )

        response = primary.post(
            reverse(
                "accounts:password_change"
            ),
            {
                "old_password":
                    self.password,
                "new_password1":
                    "Cedar!4719Galaxy",
                "new_password2":
                    "Cedar!4719Galaxy",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        user.refresh_from_db()

        self.assertTrue(
            user.check_password(
                "Cedar!4719Galaxy"
            )
        )

        new_primary_key = (
            primary.session.session_key
        )

        self.assertNotEqual(
            old_primary_key,
            new_primary_key,
        )

        self.assertTrue(
            Session.objects.filter(
                session_key=new_primary_key
            ).exists()
        )

        self.assertIn(
            "_dd_auth_started_at",
            primary.session,
        )
        self.assertIn(
            "_dd_auth_last_seen_at",
            primary.session,
        )
        self.assertEqual(
            primary.session["_dd_auth_role"],
            "USER",
        )

        self.assertFalse(
            Session.objects.filter(
                session_key=secondary_key
            ).exists()
        )

        self.assertEqual(
            primary.get(
                reverse("accounts:profile")
            ).status_code,
            200,
        )

        self.assert_login_redirect(
            secondary.get(
                reverse("accounts:profile")
            )
        )

    def test_password_reset_revokes_every_existing_authenticated_session(self):
        user = self.create_user()

        first_device = Client()
        second_device = Client()

        first_device.force_login(user)
        second_device.force_login(user)

        first_key = (
            self.activate_authenticated_session(
                first_device
            )
        )
        second_key = (
            self.activate_authenticated_session(
                second_device
            )
        )

        reset_client = Client()

        uidb64 = urlsafe_base64_encode(
            force_bytes(user.pk)
        )

        token = (
            password_reset_token_generator
            .make_token(user)
        )

        route = reverse(
            "accounts:password_reset_confirm",
            kwargs={
                "uidb64": uidb64,
                "token": token,
            },
        )

        first_response = reset_client.get(
            route
        )

        self.assertEqual(
            first_response.status_code,
            302,
        )

        response = reset_client.post(
            first_response["Location"],
            {
                "new_password1":
                    "Quartz!6591Forest",
                "new_password2":
                    "Quartz!6591Forest",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            Session.objects.filter(
                session_key=first_key
            ).exists()
        )

        self.assertFalse(
            Session.objects.filter(
                session_key=second_key
            ).exists()
        )

        self.assert_login_redirect(
            first_device.get(
                reverse("accounts:profile")
            )
        )

        self.assert_login_redirect(
            second_device.get(
                reverse("accounts:profile")
            )
        )

        self.assertNotIn(
            "_auth_user_id",
            reset_client.session,
        )

    def test_email_change_keeps_current_session_and_revokes_other_devices(self):
        user = self.create_user()

        primary = Client()
        secondary = Client()

        primary.force_login(user)
        secondary.force_login(user)

        old_primary_key = (
            self.activate_authenticated_session(
                primary
            )
        )
        secondary_key = (
            self.activate_authenticated_session(
                secondary
            )
        )

        token = make_email_change_token(
            user,
            "changed@example.com",
        )

        response = primary.post(
            reverse(
                "accounts:email_change_confirm",
                kwargs={
                    "token": token,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        user.refresh_from_db()

        self.assertEqual(
            user.email,
            "changed@example.com",
        )

        new_primary_key = (
            primary.session.session_key
        )

        self.assertNotEqual(
            old_primary_key,
            new_primary_key,
        )

        self.assertTrue(
            Session.objects.filter(
                session_key=new_primary_key
            ).exists()
        )

        self.assertIn(
            "_dd_auth_started_at",
            primary.session,
        )
        self.assertIn(
            "_dd_auth_last_seen_at",
            primary.session,
        )
        self.assertEqual(
            primary.session["_dd_auth_role"],
            "USER",
        )

        self.assertFalse(
            Session.objects.filter(
                session_key=secondary_key
            ).exists()
        )

        self.assertEqual(
            primary.get(
                reverse("accounts:profile")
            ).status_code,
            200,
        )

        self.assert_login_redirect(
            secondary.get(
                reverse("accounts:profile")
            )
        )
