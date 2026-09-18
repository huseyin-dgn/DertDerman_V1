from django.core.exceptions import (
    ImproperlyConfigured,
)
from django.test import SimpleTestCase
from sentry_sdk.integrations.logging import (
    LoggingIntegration,
)

from .sentry import (
    REDACTED,
    build_sentry_options,
    sanitize_sentry_event,
    validate_sentry_dsn,
)


class SentryConfigurationTests(
    SimpleTestCase
):
    dsn = (
        "https://public-key@"
        "o123.ingest.sentry.io/456"
    )

    def test_options_are_privacy_first(
        self,
    ):
        options = build_sentry_options(
            dsn=self.dsn,
            environment="production",
            release="test-release",
        )

        self.assertIs(
            options["send_default_pii"],
            False,
        )

        self.assertEqual(
            options[
                "max_request_body_size"
            ],
            "never",
        )

        self.assertIs(
            options[
                "include_local_variables"
            ],
            False,
        )

        self.assertIs(
            options[
                "include_source_context"
            ],
            False,
        )

        self.assertEqual(
            options[
                "max_breadcrumbs"
            ],
            0,
        )

        self.assertEqual(
            options[
                "traces_sample_rate"
            ],
            0.0,
        )

        self.assertEqual(
            options[
                "profiles_sample_rate"
            ],
            0.0,
        )

        self.assertIs(
            options[
                "enable_logs"
            ],
            False,
        )

        self.assertIs(
            options[
                "enable_tracing"
            ],
            False,
        )

        self.assertEqual(
            options[
                "trace_propagation_targets"
            ],
            [],
        )

        self.assertIn(
            LoggingIntegration,
            options[
                "disabled_integrations"
            ],
        )

    def test_event_sanitizer_removes_sensitive_values(
        self,
    ):
        secret = (
            "SECRET-TOKEN-DO-NOT-SEND"
        )

        event = {
            "user": {
                "email":
                    f"{secret}@example.com",
            },
            "request": {
                "method":
                    "POST",
                "url":
                    f"https://example.com/{secret}/",
                "data": {
                    "password":
                        secret,
                },
                "cookies": {
                    "session":
                        secret,
                },
            },
            "transaction":
                f"/confirm/{secret}/",
            "breadcrumbs": {
                "values": [
                    {
                        "message":
                            secret,
                    },
                ],
            },
            "extra": {
                "secret":
                    secret,
            },
            "tags": {
                "token":
                    secret,
            },
            "logentry": {
                "message":
                    secret,
            },
            "message":
                secret,
            "server_name":
                secret,
            "fingerprint": [
                secret,
            ],
            "exception": {
                "values": [
                    {
                        "type":
                            "RuntimeError",
                        "value":
                            secret,
                    },
                ],
            },
        }

        cleaned = sanitize_sentry_event(
            event,
            {},
        )

        serialized = repr(
            cleaned
        )

        self.assertNotIn(
            secret,
            serialized,
        )

        self.assertEqual(
            cleaned["request"],
            {
                "method":
                    "POST",
            },
        )

        self.assertEqual(
            cleaned[
                "exception"
            ][
                "values"
            ][0][
                "type"
            ],
            "RuntimeError",
        )

        self.assertEqual(
            cleaned[
                "exception"
            ][
                "values"
            ][0][
                "value"
            ],
            REDACTED,
        )

    def test_invalid_dsn_is_rejected(
        self,
    ):
        for value in (
            "",
            "not-a-dsn",
            "ftp://example.com/1",
            "https://example.com",
            "https://@example.com/1",
            "https://key@example.com/",
            "https://key@example.com/1?token=x",
        ):
            with self.subTest(
                value=value
            ):
                with self.assertRaises(
                    ImproperlyConfigured
                ):
                    validate_sentry_dsn(
                        value
                    )
