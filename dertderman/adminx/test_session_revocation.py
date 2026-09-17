from datetime import timedelta

from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils import timezone

from .permanent_closure import (
    _delete_user_sessions,
)


class SessionRevocationTests(TestCase):
    def test_corrupt_session_is_deleted_fail_closed(self):
        session = Session.objects.create(
            session_key="a" * 32,
            session_data="definitely-not-valid-session-data",
            expire_date=(
                timezone.now()
                + timedelta(hours=1)
            ),
        )

        _delete_user_sessions(
            user_id=999999
        )

        self.assertFalse(
            Session.objects.filter(
                pk=session.pk
            ).exists()
        )

    def test_valid_anonymous_session_is_not_deleted(self):
        store = SessionStore()
        store["anonymous-probe"] = "keep"
        store.save()

        session_key = store.session_key

        _delete_user_sessions(
            user_id=999999
        )

        self.assertTrue(
            Session.objects.filter(
                session_key=session_key
            ).exists()
        )
