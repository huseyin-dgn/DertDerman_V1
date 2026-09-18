from datetime import (
    datetime,
    timedelta,
    timezone as dt_timezone,
)
from importlib import import_module

from django.apps import apps as django_apps
from django.contrib.auth import (
    BACKEND_SESSION_KEY,
    HASH_SESSION_KEY,
    SESSION_KEY,
)
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils import timezone

from accounts.models import User

from .models import AuthenticatedSession


migration = import_module(
    "core.migrations."
    "0003_authenticated_session_registry"
)


class AuthenticatedSessionMigrationTests(TestCase):
    password = "MigrationSessionPassword2026!"

    def create_user(self):
        return User.objects.create_user(
            username="migration-session-user",
            email="migration-session-user@example.com",
            password=self.password,
            user_type=User.UserType.USER,
            is_active=True,
            is_verified=True,
        )

    def run_backfill(self):
        migration.backfill_authenticated_sessions(
            django_apps,
            None,
        )

    def test_backfill_registers_authenticated_session_and_preserves_timestamps(self):
        user = self.create_user()

        started_at = 1_700_000_000
        last_seen_at = 1_700_000_100

        store = SessionStore()

        store[SESSION_KEY] = str(user.pk)
        store[BACKEND_SESSION_KEY] = (
            "django.contrib.auth.backends."
            "ModelBackend"
        )
        store[HASH_SESSION_KEY] = (
            user.get_session_auth_hash()
        )

        store["_dd_auth_started_at"] = (
            started_at
        )
        store["_dd_auth_last_seen_at"] = (
            last_seen_at
        )
        store["_dd_auth_role"] = "USER"

        store.save()

        session_key = store.session_key

        self.assertFalse(
            AuthenticatedSession.objects.filter(
                session_id=session_key
            ).exists()
        )

        self.run_backfill()

        registry = (
            AuthenticatedSession.objects.get(
                session_id=session_key
            )
        )

        self.assertEqual(
            registry.user_id,
            user.pk,
        )

        self.assertEqual(
            registry.role,
            User.UserType.USER,
        )

        self.assertEqual(
            registry.created_at,
            datetime.fromtimestamp(
                started_at,
                tz=dt_timezone.utc,
            ),
        )

        self.assertEqual(
            registry.last_seen_at,
            datetime.fromtimestamp(
                last_seen_at,
                tz=dt_timezone.utc,
            ),
        )

    def test_backfill_deletes_unverifiable_session_fail_closed(self):
        session = Session.objects.create(
            session_key="b" * 32,
            session_data=(
                "definitely-invalid-session-data"
            ),
            expire_date=(
                timezone.now()
                + timedelta(hours=1)
            ),
        )

        self.run_backfill()

        self.assertFalse(
            Session.objects.filter(
                pk=session.pk
            ).exists()
        )

    def test_backfill_keeps_valid_anonymous_session_unregistered(self):
        store = SessionStore()
        store["anonymous-probe"] = "keep"
        store.save()

        session_key = store.session_key

        self.run_backfill()

        self.assertTrue(
            Session.objects.filter(
                session_key=session_key
            ).exists()
        )

        self.assertFalse(
            AuthenticatedSession.objects.filter(
                session_id=session_key
            ).exists()
        )
