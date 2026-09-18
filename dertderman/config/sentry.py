from urllib.parse import urlsplit

import sentry_sdk
from django.core.exceptions import (
    ImproperlyConfigured,
)
from sentry_sdk.integrations.logging import (
    LoggingIntegration,
)


REDACTED = "[redacted]"


def validate_sentry_dsn(value):
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError as exc:
        raise ImproperlyConfigured(
            "SENTRY_DSN must be a valid "
            "HTTP(S) Sentry DSN."
        ) from exc

    if (
        parsed.scheme not in {
            "http",
            "https",
        }
        or not parsed.hostname
        or not parsed.username
        or not parsed.path.strip("/")
        or parsed.query
        or parsed.fragment
        or any(
            character.isspace()
            for character in value
        )
    ):
        raise ImproperlyConfigured(
            "SENTRY_DSN must be a valid "
            "HTTP(S) Sentry DSN."
        )

    return value


def sanitize_sentry_event(
    event,
    hint,
):
    """
    Keep exception type + stack location while removing
    values that may contain user data, credentials or
    token-bearing request paths.
    """

    event.pop("user", None)
    event.pop("breadcrumbs", None)
    event.pop("extra", None)
    event.pop("tags", None)

    event.pop("transaction", None)
    event.pop("transaction_info", None)

    event.pop("logentry", None)
    event.pop("message", None)

    event.pop("server_name", None)
    event.pop("fingerprint", None)

    request = event.get(
        "request"
    )

    if isinstance(
        request,
        dict,
    ):
        method = request.get(
            "method"
        )

        if method:
            event["request"] = {
                "method": method,
            }
        else:
            event.pop(
                "request",
                None,
            )
    else:
        event.pop(
            "request",
            None,
        )

    exception = event.get(
        "exception"
    )

    if isinstance(
        exception,
        dict,
    ):
        values = exception.get(
            "values"
        )

        if isinstance(
            values,
            list,
        ):
            for value in values:
                if not isinstance(
                    value,
                    dict,
                ):
                    continue

                if "value" in value:
                    value[
                        "value"
                    ] = REDACTED

    return event


def build_sentry_options(
    *,
    dsn,
    environment,
    release="",
):
    validate_sentry_dsn(
        dsn
    )

    options = {
        "dsn":
            dsn,

        "environment":
            environment,

        # Error monitoring only.
        "sample_rate":
            1.0,

        "traces_sample_rate":
            0.0,

        "profiles_sample_rate":
            0.0,

        "enable_logs":
            False,

        "enable_tracing":
            False,

        "propagate_traces":
            False,

        "trace_propagation_targets":
            [],

        # Privacy.
        "send_default_pii":
            False,

        "max_request_body_size":
            "never",

        "include_local_variables":
            False,

        "include_source_context":
            False,

        "max_breadcrumbs":
            0,

        "auto_session_tracking":
            False,

        "send_client_reports":
            False,

        "attach_stacktrace":
            False,

        "max_value_length":
            1024,

        "before_send":
            sanitize_sentry_event,

        # Application logger.error() calls must not
        # automatically become Sentry issues.
        "disabled_integrations": [
            LoggingIntegration,
        ],
    }

    release = (
        release
        or ""
    ).strip()

    if release:
        options[
            "release"
        ] = release

    return options


def configure_sentry(
    *,
    dsn,
    environment,
    release="",
):
    sentry_sdk.init(
        **build_sentry_options(
            dsn=dsn,
            environment=environment,
            release=release,
        )
    )
