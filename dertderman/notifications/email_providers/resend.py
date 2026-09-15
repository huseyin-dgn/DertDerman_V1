import logging
import math
import threading
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from ..provider_identifiers import (
    ProviderMessageIdValidationError,
    validate_provider_message_id,
)


logger = logging.getLogger(__name__)
_SDK_SEND_LOCK = threading.Lock()


class ResendProviderError(RuntimeError):
    """Base error for the Resend transport adapter."""


class ResendConfigurationError(ResendProviderError):
    """Raised when the Resend adapter cannot be configured."""

    code = "provider_configuration"
    global_problem = True


class ResendDeliveryError(ResendProviderError):
    """Sanitized provider failure with an explicit retry contract."""

    def __init__(
        self,
        message="Resend delivery failed.",
        *,
        code="provider_transport_unknown",
        retryable=True,
        outcome_unknown=True,
        global_problem=False,
        retry_after_seconds=None,
    ):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.outcome_unknown = outcome_unknown
        self.global_problem = global_problem
        self.retry_after_seconds = retry_after_seconds


def _load_resend():
    try:
        import resend
    except ImportError as exc:
        raise ResendConfigurationError(
            "The resend package is not installed."
        ) from exc

    return resend


def _status_code(exc, resend):
    exceptions_module = getattr(resend, "exceptions", None)
    resend_error = getattr(exceptions_module, "ResendError", None)
    if not isinstance(resend_error, type) or not isinstance(exc, resend_error):
        return None
    try:
        return int(exc.code)
    except (TypeError, ValueError):
        return None


def _retry_after_seconds(exc, *, now=None):
    headers = getattr(exc, "headers", None)
    if not isinstance(headers, dict):
        return None
    raw_value = next(
        (
            value
            for key, value in headers.items()
            if str(key).strip().lower() == "retry-after"
        ),
        None,
    )
    if not isinstance(raw_value, str):
        return None
    value = raw_value.strip()
    if value.isascii() and value.isdigit():
        return int(value)
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at is None:
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return max(0, math.ceil((retry_at - now).total_seconds()))


def _exception_chain(exc):
    pending = [exc]
    seen = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        if current.__context__ is not None:
            pending.append(current.__context__)
        if current.__cause__ is not None:
            pending.append(current.__cause__)


def _network_failure_kind(exc):
    for current in _exception_chain(exc):
        if isinstance(current, TimeoutError):
            return "timeout"
        if isinstance(current, ConnectionError):
            return "connection"

        exception_type = current.__class__
        module_name = exception_type.__module__
        class_name = exception_type.__name__
        if module_name.startswith(("requests.", "urllib3.")):
            if "Timeout" in class_name:
                return "timeout"
            if class_name in {
                "ConnectionError",
                "ConnectError",
                "MaxRetryError",
                "NewConnectionError",
                "ProxyError",
                "SSLError",
            }:
                return "connection"
    return None


def _classify_provider_exception(exc, resend):
    network_failure = _network_failure_kind(exc)
    if network_failure == "timeout":
        return ResendDeliveryError(
            code="provider_timeout",
            retryable=True,
            outcome_unknown=True,
        )
    if network_failure == "connection":
        return ResendDeliveryError(
            code="provider_connection_error",
            retryable=True,
            outcome_unknown=True,
        )

    status = _status_code(exc, resend)
    error_type = getattr(exc, "error_type", "")
    retry_after = _retry_after_seconds(exc)

    if status == 500 and error_type == "HttpClientError":
        return ResendDeliveryError()
    if status in {401, 403}:
        return ResendDeliveryError(
            code="provider_authentication",
            retryable=False,
            outcome_unknown=False,
            global_problem=True,
        )
    if status in {400, 404, 422}:
        return ResendDeliveryError(
            code="provider_invalid_request",
            retryable=False,
            outcome_unknown=False,
        )
    if status == 409 and error_type == "invalid_idempotent_request":
        return ResendDeliveryError(
            code="provider_idempotency_conflict",
            retryable=False,
            outcome_unknown=False,
        )
    if status == 409 and error_type == "concurrent_idempotent_requests":
        return ResendDeliveryError(
            code="provider_idempotency_in_progress",
            retryable=True,
            outcome_unknown=True,
            retry_after_seconds=retry_after,
        )
    if status == 409:
        return ResendDeliveryError()
    if status == 429:
        return ResendDeliveryError(
            code="provider_rate_limited",
            retryable=True,
            outcome_unknown=False,
            retry_after_seconds=retry_after,
        )
    if status is not None and 500 <= status <= 599:
        return ResendDeliveryError(
            code="provider_server_error",
            retryable=True,
            outcome_unknown=True,
            retry_after_seconds=retry_after,
        )
    if status is not None and 400 <= status <= 499 and status != 408:
        return ResendDeliveryError(
            code="provider_invalid_request",
            retryable=False,
            outcome_unknown=False,
        )
    return ResendDeliveryError()


def _log_provider_failure(exc, resend):
    status = _status_code(exc, resend)
    if status is None:
        logger.warning(
            "Resend email request failed: exception_type=%s",
            exc.__class__.__name__,
        )
        return
    logger.warning(
        "Resend email request failed: exception_type=%s status_code=%s",
        exc.__class__.__name__,
        status,
    )


class ResendProvider:
    name = "resend"

    def __init__(self, *, api_key: str, timeout_seconds: int = 30):
        self.api_key = (api_key or "").strip()
        if not self.api_key:
            raise ResendConfigurationError("RESEND_API_KEY is missing.")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
            raise ResendConfigurationError("RESEND_TIMEOUT_SECONDS is invalid.")
        if timeout_seconds <= 0:
            raise ResendConfigurationError("RESEND_TIMEOUT_SECONDS is invalid.")
        self.timeout_seconds = timeout_seconds

    def send(
        self,
        *,
        recipient_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        from_email: str,
        reply_to: str,
        idempotency_key: str,
    ) -> str:
        resend = _load_resend()

        params = {
            "from": from_email,
            "to": [recipient_email],
            "subject": subject,
            "html": html_body,
            "text": text_body,
            "reply_to": reply_to,
        }
        options = {
            "idempotency_key": idempotency_key,
        }

        try:
            requests_client = resend.RequestsClient(timeout=self.timeout_seconds)
        except Exception as exc:
            raise ResendConfigurationError(
                "The Resend HTTP client could not be configured."
            ) from exc

        try:
            # resend-python 2.44.0 exposes API credentials and its default HTTP
            # transport as module globals. Serialize adapter-owned mutations so
            # concurrent sends through this adapter cannot interleave them.
            with _SDK_SEND_LOCK:
                previous_api_key = resend.api_key
                previous_http_client = resend.default_http_client
                try:
                    resend.api_key = self.api_key
                    resend.default_http_client = requests_client
                    response = resend.Emails.send(params, options=options)
                finally:
                    resend.api_key = previous_api_key
                    resend.default_http_client = previous_http_client
        except ResendProviderError:
            raise
        except Exception as exc:
            # Do not log message bodies, token-bearing URLs, recipient addresses,
            # provider credentials or raw provider error payloads here.
            _log_provider_failure(exc, resend)
            raise _classify_provider_exception(exc, resend) from exc

        provider_message_id = (
            response.get("id")
            if isinstance(response, dict)
            else getattr(response, "id", None)
        )

        try:
            return validate_provider_message_id(provider_message_id)
        except ProviderMessageIdValidationError as exc:
            raise ResendDeliveryError(
                "Resend response included an invalid message id.",
                code="provider_invalid_response",
                retryable=True,
                outcome_unknown=True,
            ) from exc
