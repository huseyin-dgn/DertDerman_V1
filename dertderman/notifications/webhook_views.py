import logging

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .webhook_security import (
    ResendWebhookConfigurationError,
    ResendWebhookVerificationError,
    verify_resend_webhook,
)
from .webhook_service import ResendWebhookPayloadError, process_resend_webhook

logger = logging.getLogger(__name__)


def _resend_webhook_max_body_bytes():
    value = getattr(settings, "RESEND_WEBHOOK_MAX_BODY_BYTES", 131072)
    if isinstance(value, bool):
        raise ResendWebhookConfigurationError(
            "RESEND_WEBHOOK_MAX_BODY_BYTES must be a positive integer."
        )
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ResendWebhookConfigurationError(
            "RESEND_WEBHOOK_MAX_BODY_BYTES must be a positive integer."
        ) from None
    if value <= 0:
        raise ResendWebhookConfigurationError(
            "RESEND_WEBHOOK_MAX_BODY_BYTES must be a positive integer."
        )
    return value


@csrf_exempt
@never_cache
@require_POST
def resend_webhook(request):
    """Public callback; CSRF yerine provider imzası zorunludur."""
    try:
        max_bytes = _resend_webhook_max_body_bytes()
    except ResendWebhookConfigurationError as exc:
        logger.error(
            "Resend webhook config error: exception_type=%s",
            exc.__class__.__name__,
        )
        return HttpResponse(status=503)

    content_length = request.META.get("CONTENT_LENGTH")
    if content_length:
        try:
            content_length = int(content_length)
            if content_length < 0:
                return HttpResponse(status=400)
            if content_length > max_bytes:
                return HttpResponse(status=413)
        except (TypeError, ValueError):
            return HttpResponse(status=400)

    try:
        raw_body = request.read(max_bytes + 1)
    except OSError:
        return HttpResponse(status=400)
    if len(raw_body) > max_bytes:
        return HttpResponse(status=413)

    svix_id = request.headers.get("svix-id", "")
    try:
        payload = verify_resend_webhook(
            raw_body=raw_body,
            svix_id=svix_id,
            svix_timestamp=request.headers.get("svix-timestamp", ""),
            svix_signature=request.headers.get("svix-signature", ""),
        )
    except ResendWebhookConfigurationError as exc:
        logger.error("Resend webhook config error: exception_type=%s", exc.__class__.__name__)
        return HttpResponse(status=503)
    except ResendWebhookVerificationError:
        return HttpResponse(status=400)

    try:
        process_resend_webhook(event_id=svix_id, payload=payload)
    except ResendWebhookPayloadError:
        return HttpResponse(status=400)
    except Exception as exc:
        logger.error("Resend webhook processing failed: exception_type=%s", exc.__class__.__name__)
        return HttpResponse(status=500)

    return HttpResponse(status=200)
