from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from core.session_security import (
    SESSION_REAUTH_AT_KEY,
    has_recent_reauthentication,
    mark_reauthenticated,
)


@override_settings(
    AUTH_SESSION_REAUTH_MAX_AGE_SECONDS=300,
)
class RecentAuthenticationTests(SimpleTestCase):
    def test_mark_and_validate_recent_authentication(self):
        session = {}

        with patch(
            "core.session_security.time.time",
            return_value=1000,
        ):
            self.assertTrue(
                mark_reauthenticated(session)
            )

        self.assertEqual(
            session[SESSION_REAUTH_AT_KEY],
            1000,
        )

        self.assertTrue(
            has_recent_reauthentication(
                session,
                now=1299,
            )
        )

        self.assertFalse(
            has_recent_reauthentication(
                session,
                now=1300,
            )
        )

    def test_missing_invalid_or_future_timestamp_fails_closed(self):
        self.assertFalse(
            has_recent_reauthentication(
                {},
                now=1000,
            )
        )

        self.assertFalse(
            has_recent_reauthentication(
                {
                    SESSION_REAUTH_AT_KEY:
                        "invalid",
                },
                now=1000,
            )
        )

        self.assertFalse(
            has_recent_reauthentication(
                {
                    SESSION_REAUTH_AT_KEY:
                        1001,
                },
                now=1000,
            )
        )
