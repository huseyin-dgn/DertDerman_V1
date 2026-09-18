import logging


class SafeFrameworkRequestFilter(logging.Filter):
    """
    Django request/security log records may contain request paths.

    Some DertDerman routes contain short-lived authentication tokens
    in the URL path. Replace framework-generated messages with a
    minimal structured event before they reach production logs.
    """

    def filter(self, record):
        request = getattr(
            record,
            "request",
            None,
        )

        method = (
            getattr(
                request,
                "method",
                None,
            )
            or "UNKNOWN"
        )

        status_code = getattr(
            record,
            "status_code",
            None,
        )

        if status_code is None:
            status_code = "unknown"

        exception_type = "none"

        if (
            record.exc_info
            and record.exc_info[0]
        ):
            exception_type = (
                record.exc_info[0].__name__
            )

        record.msg = (
            "Framework request event: "
            "method=%s "
            "status_code=%s "
            "exception_type=%s"
        )

        record.args = (
            method,
            status_code,
            exception_type,
        )

        # Raw exception messages may themselves contain request
        # or infrastructure details.
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None

        return True
