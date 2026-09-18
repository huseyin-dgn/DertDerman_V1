import logging
import sys
from types import SimpleNamespace

from django.test import SimpleTestCase

from .logging_filters import (
    SafeFrameworkRequestFilter,
)


class SafeFrameworkRequestFilterTests(
    SimpleTestCase
):
    def test_token_bearing_path_is_removed(
        self,
    ):
        secret = (
            "SUPER-SECRET-TOKEN-"
            "DO-NOT-LOG"
        )

        try:
            raise RuntimeError(
                secret
            )
        except RuntimeError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="django.request",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg=(
                "Internal Server Error: "
                f"/hesap/eposta-dogrula/{secret}/"
            ),
            args=(),
            exc_info=exc_info,
        )

        record.request = (
            SimpleNamespace(
                method="GET",
            )
        )

        record.status_code = 500

        SafeFrameworkRequestFilter().filter(
            record
        )

        message = record.getMessage()

        self.assertNotIn(
            secret,
            message,
        )

        self.assertEqual(
            message,
            (
                "Framework request event: "
                "method=GET "
                "status_code=500 "
                "exception_type=RuntimeError"
            ),
        )

        self.assertIsNone(
            record.exc_info
        )

    def test_filter_handles_missing_request_metadata(
        self,
    ):
        record = logging.LogRecord(
            name=(
                "django.security."
                "DisallowedHost"
            ),
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg="unsafe original message",
            args=(),
            exc_info=None,
        )

        SafeFrameworkRequestFilter().filter(
            record
        )

        self.assertEqual(
            record.getMessage(),
            (
                "Framework request event: "
                "method=UNKNOWN "
                "status_code=unknown "
                "exception_type=none"
            ),
        )
