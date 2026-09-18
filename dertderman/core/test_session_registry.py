from datetime import timedelta

from django.contrib.sessions.models import Session
from django.test import (
    Client,
    TestCase,
    override_settings,
)
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from .models import AuthenticatedSession


TEST_MAX_ACTIVE = {
    "USER": 2,
    "COMPANY": 2,
    "ADMIN": 1,
}


@override_settings(
    AUTH_SESSION_SECURITY_ENABLED=True,
    AUTH_SESSION_MAX_ACTIVE_SESSIONS=TEST_MAX_ACTIVE,
)
class AuthenticatedSessionRegistryTests(TestCase):
    password = "RegistryPassword2026!"

    def create_user(self):
        return User.objects.create_user(
            username="registry-user",
            email="registry-user@example.com",
            password=self.password,
            user_type=User.UserType.USER,
            is_active=True,
            is_verified=True,
        )

    def activate(self, client, user):
        client.force_login(user)

        response = client.get(
            reverse("accounts:profile")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        return client.session.session_key

    def test_session_limit_evicts_oldest_registered_session(self):
        user = self.create_user()

        first = Client()
        second = Client()
        third = Client()

        first_key = self.activate(
            first,
            user,
        )

        AuthenticatedSession.objects.filter(
            session_id=first_key
        ).update(
            created_at=(
                timezone.now()
                - timedelta(minutes=2)
            )
        )

        second_key = self.activate(
            second,
            user,
        )

        AuthenticatedSession.objects.filter(
            session_id=second_key
        ).update(
            created_at=(
                timezone.now()
                - timedelta(minutes=1)
            )
        )

        third_key = self.activate(
            third,
            user,
        )

        self.assertFalse(
            Session.objects.filter(
                session_key=first_key
            ).exists()
        )

        self.assertTrue(
            Session.objects.filter(
                session_key=second_key
            ).exists()
        )

        self.assertTrue(
            Session.objects.filter(
                session_key=third_key
            ).exists()
        )

        self.assertEqual(
            AuthenticatedSession.objects.filter(
                user=user
            ).count(),
            2,
        )

        expired_client_response = first.get(
            reverse("accounts:profile")
        )

        self.assertEqual(
            expired_client_response.status_code,
            302,
        )

        self.assertIn(
            reverse("accounts:login"),
            expired_client_response[
                "Location"
            ],
        )

    def test_existing_registered_overflow_is_trimmed_on_first_request(self):
        user = self.create_user()

        clients = [
            Client(),
            Client(),
            Client(),
        ]

        session_keys = []

        # force_login burada yalnız test fixture oluşturuyor.
        # Registry kayıtlarını deployment backfill sonucuna benzer
        # şekilde elle hazırlıyoruz.
        for client in clients:
            client.force_login(user)

            session_key = (
                client.session.session_key
            )

            session_keys.append(
                session_key
            )

            AuthenticatedSession.objects.create(
                session_id=session_key,
                user=user,
                role=User.UserType.USER,
            )

        self.assertEqual(
            AuthenticatedSession.objects.filter(
                user=user
            ).count(),
            3,
        )

        response = clients[0].get(
            reverse("accounts:profile")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        # USER limiti bu testte 2. Mevcut aktif request korunur,
        # diğer eski session'lardan biri kaldırılır.
        self.assertEqual(
            AuthenticatedSession.objects.filter(
                user=user
            ).count(),
            2,
        )

        self.assertTrue(
            Session.objects.filter(
                session_key=session_keys[0]
            ).exists()
        )

    def test_password_change_rotates_registry_to_new_session_key(self):
        user = self.create_user()

        client = Client()

        old_key = self.activate(
            client,
            user,
        )

        response = client.post(
            reverse(
                "accounts:password_change"
            ),
            {
                "old_password":
                    self.password,
                "new_password1":
                    "RegistryNewPassword2027!",
                "new_password2":
                    "RegistryNewPassword2027!",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        new_key = (
            client.session.session_key
        )

        self.assertNotEqual(
            old_key,
            new_key,
        )

        self.assertFalse(
            AuthenticatedSession.objects.filter(
                session_id=old_key
            ).exists()
        )

        self.assertTrue(
            AuthenticatedSession.objects.filter(
                session_id=new_key,
                user=user,
                role=User.UserType.USER,
            ).exists()
        )
