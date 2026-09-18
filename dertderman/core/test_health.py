from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse


class HealthEndpointTests(TestCase):
    def test_liveness_returns_200(self):
        response = self.client.get(
            reverse("core:health_live")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.json(),
            {
                "status": "ok",
            },
        )

        self.assertIn(
            "no-cache",
            response.headers[
                "Cache-Control"
            ],
        )

    def test_liveness_accepts_head(self):
        response = self.client.head(
            reverse("core:health_live")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_liveness_rejects_post(self):
        response = self.client.post(
            reverse("core:health_live")
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_readiness_returns_200_when_dependencies_are_available(self):
        response = self.client.get(
            reverse("core:health_ready")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response.json(),
            {
                "status": "ok",
            },
        )

    @patch(
        "core.health.connection.cursor",
        side_effect=RuntimeError(
            "database unavailable"
        ),
    )
    def test_readiness_returns_503_when_database_is_unavailable(
        self,
        mocked_cursor,
    ):
        response = self.client.get(
            reverse("core:health_ready")
        )

        self.assertEqual(
            response.status_code,
            503,
        )

        self.assertEqual(
            response.json(),
            {
                "status": "unavailable",
            },
        )

        self.assertNotContains(
            response,
            "database unavailable",
            status_code=503,
        )

    @patch(
        "core.health.cache.get",
        side_effect=RuntimeError(
            "cache unavailable"
        ),
    )
    def test_readiness_returns_503_when_cache_is_unavailable(
        self,
        mocked_cache,
    ):
        response = self.client.get(
            reverse("core:health_ready")
        )

        self.assertEqual(
            response.status_code,
            503,
        )

        self.assertEqual(
            response.json(),
            {
                "status": "unavailable",
            },
        )

        self.assertNotContains(
            response,
            "cache unavailable",
            status_code=503,
        )


class HealthLoggingSafetyTests(TestCase):
    def test_dependency_exception_messages_are_not_logged(
        self,
    ):
        database_secret = (
            "postgres-password-DO-NOT-LOG"
        )

        cache_secret = (
            "redis-secret-DO-NOT-LOG"
        )

        with (
            patch(
                "core.health.connection.cursor",
                side_effect=RuntimeError(
                    database_secret
                ),
            ),
            patch(
                "core.health.cache.get",
                side_effect=ValueError(
                    cache_secret
                ),
            ),
            patch(
                "core.health.logger.error"
            ) as mocked_logger,
        ):
            response = self.client.get(
                reverse(
                    "core:health_ready"
                )
            )

        self.assertEqual(
            response.status_code,
            503,
        )

        logged = repr(
            mocked_logger.call_args_list
        )

        self.assertNotIn(
            database_secret,
            logged,
        )

        self.assertNotIn(
            cache_secret,
            logged,
        )

        self.assertIn(
            "RuntimeError",
            logged,
        )

        self.assertIn(
            "ValueError",
            logged,
        )
