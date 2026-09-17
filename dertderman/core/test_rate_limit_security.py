from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from .rate_limit import (
    AuthRateLimitPolicy,
    build_rate_limit_key,
    auth_rate_limit_status,
    clear_auth_identity,
    consume_auth_failure,
    consume_rate_limit,
)


@override_settings(
    RATE_LIMIT_ENABLED=True,
    SECRET_KEY=(
        "rate-limit-security-test-secret-"
        "with-sufficient-entropy-2026"
    ),
)
class RateLimitSecurityTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_cache_key_uses_keyed_digest_and_hides_identifier(self):
        identifier = "Sensitive.User@example.com"

        key = build_rate_limit_key(
            scope="security-test",
            identifier=identifier,
        )

        self.assertTrue(
            key.startswith(
                "dertderman:rl:v2:"
            )
        )
        self.assertNotIn(
            "Sensitive.User",
            key,
        )
        self.assertNotIn(
            "example.com",
            key,
        )

    def test_backend_failure_fails_closed(self):
        with patch(
            "core.rate_limit.cache.add",
            side_effect=RuntimeError(
                "cache unavailable"
            ),
        ):
            result = consume_rate_limit(
                scope="security-test",
                identifier="user@example.com",
                limit=5,
                window_seconds=900,
            )

        self.assertFalse(result.allowed)
        self.assertEqual(result.retry_after, 900)

    def test_auth_status_check_does_not_consume_quota(self):
        policy = AuthRateLimitPolicy(
            pair_limit=1,
            pair_window_seconds=900,
            identity_limit=1,
            identity_window_seconds=3600,
            ip_limit=1,
            ip_window_seconds=900,
        )

        for _ in range(5):
            status = auth_rate_limit_status(
                scope="status-test",
                ip_address="192.0.2.20",
                identity="known-user",
                policy=policy,
            )
            self.assertTrue(status.allowed)

        first_failure = consume_auth_failure(
            scope="status-test",
            ip_address="192.0.2.20",
            identity="known-user",
            policy=policy,
        )

        self.assertTrue(first_failure.allowed)

        blocked = auth_rate_limit_status(
            scope="status-test",
            ip_address="192.0.2.20",
            identity="known-user",
            policy=policy,
        )

        self.assertFalse(blocked.allowed)

    def test_auth_status_backend_failure_fails_closed(self):
        policy = AuthRateLimitPolicy(
            pair_limit=5,
            pair_window_seconds=900,
            identity_limit=10,
            identity_window_seconds=3600,
            ip_limit=20,
            ip_window_seconds=900,
        )

        with patch(
            "core.rate_limit.cache.get",
            side_effect=RuntimeError(
                "cache unavailable"
            ),
        ):
            result = auth_rate_limit_status(
                scope="status-failure-test",
                ip_address="192.0.2.30",
                identity="known-user",
                policy=policy,
            )

        self.assertFalse(result.allowed)
        self.assertGreater(
            result.retry_after,
            0,
        )

    def test_identity_limit_survives_source_ip_rotation(self):
        policy = AuthRateLimitPolicy(
            pair_limit=2,
            pair_window_seconds=900,
            identity_limit=3,
            identity_window_seconds=3600,
            ip_limit=10,
            ip_window_seconds=900,
        )

        for index in range(3):
            result = consume_auth_failure(
                scope="rotation-test",
                ip_address=f"192.0.2.{index + 1}",
                identity="victim",
                policy=policy,
            )
            self.assertTrue(result.allowed)

        blocked = consume_auth_failure(
            scope="rotation-test",
            ip_address="192.0.2.99",
            identity="victim",
            policy=policy,
        )

        self.assertFalse(blocked.allowed)
        self.assertEqual(
            blocked.retry_after,
            3600,
        )

    def test_success_clears_pair_and_identity_but_not_ip_bucket(self):
        policy = AuthRateLimitPolicy(
            pair_limit=2,
            pair_window_seconds=900,
            identity_limit=2,
            identity_window_seconds=3600,
            ip_limit=10,
            ip_window_seconds=900,
        )

        for _ in range(2):
            self.assertTrue(
                consume_auth_failure(
                    scope="clear-test",
                    ip_address="192.0.2.5",
                    identity="known-user",
                    policy=policy,
                ).allowed
            )

        clear_auth_identity(
            scope="clear-test",
            ip_address="192.0.2.5",
            identity="known-user",
        )

        # Without the successful-login clear, the third account
        # attempt would exceed identity_limit=2.
        self.assertTrue(
            consume_auth_failure(
                scope="clear-test",
                ip_address="192.0.2.5",
                identity="known-user",
                policy=policy,
            ).allowed
        )
