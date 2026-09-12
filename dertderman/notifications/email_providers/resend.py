import logging


logger = logging.getLogger(__name__)


class ResendProviderError(RuntimeError):
    """Base error for the Resend transport adapter."""


class ResendConfigurationError(ResendProviderError):
    """Raised when the Resend adapter cannot be configured."""


class ResendDeliveryError(ResendProviderError):
    """Raised when Resend rejects or fails an email request."""


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
        except Exception as exc:
            # Do not log message bodies, token-bearing URLs, recipient addresses,
            # provider credentials or raw provider error payloads here.
            logger.warning(
                "Resend email request failed: exception_type=%s",
                exc.__class__.__name__,
            )
            raise ResendDeliveryError("Resend delivery failed.") from exc

        provider_message_id = (
            response.get("id")
            if isinstance(response, dict)
            else getattr(response, "id", None)
        )

        if not provider_message_id:
            raise ResendDeliveryError(
                "Resend response did not include a message id."
            )

        return str(provider_message_id)
