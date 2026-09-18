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
