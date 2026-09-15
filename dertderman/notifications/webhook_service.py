from datetime import timezone as datetime_timezone

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import EmailDelivery, EmailWebhookEvent
from .provider_identifiers import (
    ProviderMessageIdValidationError,
    validate_provider_message_id,
)


class ResendWebhookPayloadError(ValueError):
    """Doğrulanmış event yapısal olarak kullanılamadığında oluşur."""


class ResendWebhookIntegrityError(RuntimeError):
    """Raised when delivery ownership invariants are violated."""


_PROVIDER_STATUS_BY_EVENT = {
    "email.sent": EmailDelivery.ProviderStatus.SENT,
    "email.delivered": EmailDelivery.ProviderStatus.DELIVERED,
    "email.delivery_delayed": EmailDelivery.ProviderStatus.DELAYED,
    "email.bounced": EmailDelivery.ProviderStatus.BOUNCED,
    "email.complained": EmailDelivery.ProviderStatus.COMPLAINED,
    "email.failed": EmailDelivery.ProviderStatus.FAILED,
    "email.suppressed": EmailDelivery.ProviderStatus.SUPPRESSED,
}

# Equal provider timestamps need a deterministic tie-breaker. This ordering is
# used only for equal timestamps; every legitimate later event still wins.
_PROVIDER_STATUS_PRECEDENCE = {
    EmailDelivery.ProviderStatus.SENT: 10,
    EmailDelivery.ProviderStatus.DELAYED: 20,
    EmailDelivery.ProviderStatus.DELIVERED: 30,
    EmailDelivery.ProviderStatus.FAILED: 40,
    EmailDelivery.ProviderStatus.SUPPRESSED: 50,
    EmailDelivery.ProviderStatus.BOUNCED: 60,
    EmailDelivery.ProviderStatus.COMPLAINED: 70,
}


def _event_time(value, *, required=False):
    if not isinstance(value, str) or not value.strip():
        if required:
            raise ResendWebhookPayloadError(
                "Tracked email event is missing a valid created_at."
            )
        return timezone.now()
    parsed = parse_datetime(value.strip())
    if parsed is None:
        if required:
            raise ResendWebhookPayloadError(
                "Tracked email event has an invalid created_at."
            )
        return timezone.now()
    if timezone.is_naive(parsed):
        parsed = parsed.replace(tzinfo=datetime_timezone.utc)
    return parsed


def _extract(payload):
    if not isinstance(payload, dict):
        raise ResendWebhookPayloadError("Payload must be an object.")
    raw_event_type = payload.get("type")
    if not isinstance(raw_event_type, str):
        raise ResendWebhookPayloadError("Invalid event type.")
    event_type = raw_event_type.strip()
    if not event_type or len(event_type) > 64:
        raise ResendWebhookPayloadError("Invalid event type.")
    data = payload.get("data", {})
    if not isinstance(data, dict):
        raise ResendWebhookPayloadError("Invalid event data.")
    if "email_id" in data:
        try:
            message_id = validate_provider_message_id(data["email_id"])
        except ProviderMessageIdValidationError as exc:
            raise ResendWebhookPayloadError(
                "Invalid provider message id."
            ) from exc
    else:
        message_id = ""
    provider_status = _PROVIDER_STATUS_BY_EVENT.get(event_type)
    if provider_status and not message_id:
        raise ResendWebhookPayloadError("Tracked email event is missing email_id.")
    event_created_at = _event_time(
        payload.get("created_at"),
        required=provider_status is not None,
    )
    return event_type, message_id, provider_status, event_created_at


def _match_delivery(message_id):
    message_id = validate_provider_message_id(message_id)
    try:
        return EmailDelivery.objects.select_for_update().get(
            provider="resend",
            provider_message_id=message_id,
        )
    except EmailDelivery.DoesNotExist:
        return None
    except EmailDelivery.MultipleObjectsReturned as exc:
        raise ResendWebhookIntegrityError(
            "Provider message ownership is not unique."
        ) from exc


def _apply_status(delivery, provider_status, event_created_at):
    current_at = delivery.provider_status_at
    if current_at is not None and event_created_at < current_at:
        return False
    if current_at is not None and event_created_at == current_at:
        current_precedence = _PROVIDER_STATUS_PRECEDENCE.get(
            delivery.provider_status,
            0,
        )
        incoming_precedence = _PROVIDER_STATUS_PRECEDENCE[provider_status]
        if incoming_precedence <= current_precedence:
            return False
    delivery.provider_status = provider_status
    delivery.provider_status_at = event_created_at
    delivery.save(update_fields=["provider_status", "provider_status_at", "updated_at"])
    return True


def _assert_duplicate_consistency(
    existing,
    *,
    event_type,
    message_id,
    provider_status,
    event_created_at,
):
    metadata_matches = (
        existing.provider == "resend"
        and existing.event_type == event_type
        and existing.provider_message_id == message_id
    )
    if provider_status is not None:
        metadata_matches = (
            metadata_matches
            and existing.event_created_at == event_created_at
        )
    if not metadata_matches:
        raise ResendWebhookIntegrityError(
            "Webhook event identity conflicts with stored metadata."
        )


@transaction.atomic
def process_resend_webhook(*, event_id: str, payload: dict):
    event_id = (event_id or "").strip()
    if not event_id or len(event_id) > 255:
        raise ResendWebhookPayloadError("Invalid webhook event id.")

    event_type, message_id, provider_status, event_created_at = _extract(payload)

    existing = (EmailWebhookEvent.objects.select_for_update()
                .filter(event_id=event_id).first())
    if existing is not None:
        _assert_duplicate_consistency(
            existing,
            event_type=event_type,
            message_id=message_id,
            provider_status=provider_status,
            event_created_at=event_created_at,
        )
        if (existing.processing_result == EmailWebhookEvent.ProcessingResult.UNMATCHED
                and existing.provider_message_id):
            delivery = _match_delivery(existing.provider_message_id)
            mapped = _PROVIDER_STATUS_BY_EVENT.get(existing.event_type)
            if delivery is not None and mapped:
                _apply_status(delivery, mapped, existing.event_created_at or existing.received_at)
                existing.delivery = delivery
                existing.processing_result = EmailWebhookEvent.ProcessingResult.MATCHED
                existing.save(update_fields=["delivery", "processing_result"])
        return existing, False

    result = EmailWebhookEvent.ProcessingResult.IGNORED
    delivery = None
    if provider_status:
        delivery = _match_delivery(message_id)
        if delivery is None:
            result = EmailWebhookEvent.ProcessingResult.UNMATCHED
        else:
            _apply_status(delivery, provider_status, event_created_at)
            result = EmailWebhookEvent.ProcessingResult.MATCHED

    event = EmailWebhookEvent.objects.create(
        provider="resend",
        event_id=event_id,
        event_type=event_type,
        provider_message_id=message_id,
        delivery=delivery,
        processing_result=result,
        event_created_at=event_created_at,
    )
    return event, True


@transaction.atomic
def reconcile_unmatched_resend_events(provider_message_id: str) -> int:
    provider_message_id = validate_provider_message_id(provider_message_id)
    delivery = _match_delivery(provider_message_id)
    if delivery is None:
        return 0
    events = list(
        EmailWebhookEvent.objects.select_for_update().filter(
            provider="resend",
            provider_message_id=provider_message_id,
            processing_result=EmailWebhookEvent.ProcessingResult.UNMATCHED,
            delivery__isnull=True,
        ).order_by("event_created_at", "received_at", "pk")
    )
    for event in events:
        mapped = _PROVIDER_STATUS_BY_EVENT.get(event.event_type)
        if mapped:
            _apply_status(delivery, mapped, event.event_created_at or event.received_at)
        event.delivery = delivery
        event.processing_result = EmailWebhookEvent.ProcessingResult.MATCHED
        event.save(update_fields=["delivery", "processing_result"])
    return len(events)
