import logging


logger = logging.getLogger(__name__)


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


class ResendProvider:
    name = "resend"

    def __init__(self, *, api_key: str):
        self.api_key = (api_key or "").strip()
        if not self.api_key:
            raise ResendConfigurationError("RESEND_API_KEY is missing.")

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
        resend.api_key = self.api_key

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
            response = resend.Emails.send(params, options=options)
        except (TimeoutError, ConnectionError) as exc:
            logger.warning(
                "Resend email request failed: exception_type=%s",
                exc.__class__.__name__,
            )
            raise ResendDeliveryError(
                code="provider_network_error",
                retryable=True,
                outcome_unknown=True,
            ) from exc
        except ResendProviderError:
            raise
        except Exception as exc:
            # Do not log message bodies, token-bearing URLs, recipient addresses,
            # provider credentials or raw provider error payloads here.
            logger.warning(
                "Resend email request failed: exception_type=%s",
                exc.__class__.__name__,
            )
            # The SDK is optional and its exception contract is not available
            # in this repository. Unknown SDK failures are therefore treated
            # as transient/ambiguous rather than guessing at private fields.
            raise ResendDeliveryError() from exc

        provider_message_id = (
            response.get("id")
            if isinstance(response, dict)
            else getattr(response, "id", None)
        )

        if not provider_message_id:
            raise ResendDeliveryError(
                "Resend response did not include a message id.",
                code="provider_invalid_response",
                retryable=True,
                outcome_unknown=True,
            )

        return str(provider_message_id)
