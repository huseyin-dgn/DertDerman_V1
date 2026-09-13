from django.conf import settings


class ResendWebhookError(RuntimeError):
    """Base error for the Resend webhook boundary."""


class ResendWebhookConfigurationError(ResendWebhookError):
    """Webhook doğrulaması yapılandırılamadığında oluşur."""


class ResendWebhookVerificationError(ResendWebhookError):
    """İmza veya doğrulanmış payload geçersiz olduğunda oluşur."""


def _load_resend():
    try:
        import resend
    except ImportError as exc:
        raise ResendWebhookConfigurationError(
            "The resend package is not installed."
        ) from exc
    return resend


def verify_resend_webhook(*, raw_body: bytes, svix_id: str, svix_timestamp: str, svix_signature: str) -> dict:
    """Ham request body'yi resmi Resend SDK ile doğrula."""
    secret = getattr(settings, "RESEND_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise ResendWebhookConfigurationError("RESEND_WEBHOOK_SECRET is missing.")
    if not svix_id or not svix_timestamp or not svix_signature:
        raise ResendWebhookVerificationError("Required signature headers are missing.")

    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResendWebhookVerificationError("Payload is not UTF-8.") from exc

    resend = _load_resend()
    verify = getattr(getattr(resend, "Webhooks", None), "verify", None)
    if not callable(verify):
        raise ResendWebhookConfigurationError(
            "Installed resend SDK does not support Webhooks.verify."
        )

    try:
        result = verify({
            "payload": payload,
            "headers": {
                "id": svix_id,
                "timestamp": svix_timestamp,
                "signature": svix_signature,
            },
            "webhook_secret": secret,
        })
    except Exception as exc:
        raise ResendWebhookVerificationError("Webhook verification failed.") from exc

    if not isinstance(result, dict):
        raise ResendWebhookVerificationError("Verified payload has an invalid shape.")
    return result
