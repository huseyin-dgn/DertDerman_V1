from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import Mock, patch

from django.db import transaction
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .models import EmailDelivery, EmailWebhookEvent
from .webhook_security import (
    ResendWebhookConfigurationError,
    ResendWebhookVerificationError,
    verify_resend_webhook,
)
from .webhook_service import (
    ResendWebhookIntegrityError,
    ResendWebhookPayloadError,
    process_resend_webhook,
    reconcile_unmatched_resend_events,
)
from .provider_identifiers import PROVIDER_MESSAGE_ID_MAX_LENGTH


@override_settings(RESEND_WEBHOOK_SECRET="whsec_test_only", RESEND_WEBHOOK_MAX_BODY_BYTES=131072)
class ResendWebhookTests(TestCase):
    def setUp(self):
        self.url = reverse("notification_webhooks:resend")
        self.delivery = EmailDelivery.objects.create(
            provider="resend",
            idempotency_key="dertderman/test-stage8",
            recipient_hash="a" * 64,
            status=EmailDelivery.Status.SENT,
            provider_message_id="email_stage8_123",
            attempt_count=1,
        )

    def payload(self, event_type="email.delivered", created_at="2026-09-13T12:00:00Z", email_id=None):
        return {
            "type": event_type,
            "created_at": created_at,
            "data": {
                "email_id": email_id or self.delivery.provider_message_id,
                "to": ["private-person@example.com"],
                "subject": "PRIVATE SUBJECT",
            },
        }

    def post_verified(self, event_id, payload):
        with patch("notifications.webhook_views.verify_resend_webhook", return_value=payload):
            return self.client.post(
                self.url,
                data=b'{"raw":"body"}',
                content_type="application/json",
                HTTP_SVIX_ID=event_id,
                HTTP_SVIX_TIMESTAMP="1789290000",
                HTTP_SVIX_SIGNATURE="v1,test",
            )

    def test_delivered_updates_status_and_minimal_audit(self):
        r = self.post_verified("msg_delivered", self.payload())
        self.assertEqual(r.status_code, 200)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.provider_status, EmailDelivery.ProviderStatus.DELIVERED)
        event = EmailWebhookEvent.objects.get(event_id="msg_delivered")
        self.assertEqual(event.processing_result, EmailWebhookEvent.ProcessingResult.MATCHED)
        stored = " ".join(str(v) for v in EmailWebhookEvent.objects.values().first().values())
        self.assertNotIn("private-person@example.com", stored)
        self.assertNotIn("PRIVATE SUBJECT", stored)

    def test_capacity_length_id_matches_and_is_stored_exactly(self):
        provider_message_id = "x" * PROVIDER_MESSAGE_ID_MAX_LENGTH
        self.delivery.provider_message_id = provider_message_id
        self.delivery.save(update_fields=["provider_message_id"])

        response = self.post_verified(
            "msg_capacity_id",
            self.payload(email_id=provider_message_id),
        )

        self.assertEqual(response.status_code, 200)
        event = EmailWebhookEvent.objects.get(event_id="msg_capacity_id")
        self.assertEqual(event.provider_message_id, provider_message_id)
        self.assertEqual(event.delivery_id, self.delivery.pk)

    def test_duplicate_svix_id_is_idempotent(self):
        payload = self.payload()
        self.assertEqual(self.post_verified("msg_dup", payload).status_code, 200)
        self.assertEqual(self.post_verified("msg_dup", payload).status_code, 200)
        self.assertEqual(EmailWebhookEvent.objects.filter(event_id="msg_dup").count(), 1)

    def test_conflicting_duplicate_event_id_raises_integrity_alarm(self):
        event, created = process_resend_webhook(
            event_id="msg_conflicting_duplicate",
            payload=self.payload(),
        )
        self.assertTrue(created)
        original_metadata = (
            event.event_type,
            event.provider_message_id,
            event.event_created_at,
            event.delivery_id,
            event.processing_result,
        )
        conflicting_payloads = (
            self.payload("email.bounced"),
            self.payload(email_id="private-conflicting-provider-id"),
            self.payload(created_at="2026-09-13T12:00:01Z"),
        )

        with transaction.atomic():
            for payload in conflicting_payloads:
                with self.subTest(conflict=payload), self.assertRaises(
                    ResendWebhookIntegrityError
                ) as captured:
                    process_resend_webhook(
                        event_id="msg_conflicting_duplicate",
                        payload=payload,
                    )
                self.assertNotIn(
                    "private-conflicting-provider-id",
                    str(captured.exception),
                )

            # The caller's transaction remains usable after every alarm.
            self.assertEqual(EmailWebhookEvent.objects.count(), 1)
            event.refresh_from_db()

        self.assertEqual(
            (
                event.event_type,
                event.provider_message_id,
                event.event_created_at,
                event.delivery_id,
                event.processing_result,
            ),
            original_metadata,
        )

    def test_conflicting_duplicate_returns_retryable_500_without_private_data(self):
        event_id = "msg_conflicting_duplicate_http"
        self.assertEqual(
            self.post_verified(event_id, self.payload()).status_code,
            200,
        )
        private_provider_id = "private-conflicting-http-provider-id"

        with self.assertLogs(
            "notifications.webhook_views",
            level="ERROR",
        ) as captured:
            response = self.post_verified(
                event_id,
                self.payload(email_id=private_provider_id),
            )

        self.assertEqual(response.status_code, 500)
        self.assertNotIn(private_provider_id, response.content.decode())
        self.assertNotIn(private_provider_id, " ".join(captured.output))
        event = EmailWebhookEvent.objects.get(event_id=event_id)
        self.assertEqual(
            event.provider_message_id,
            self.delivery.provider_message_id,
        )

    def test_invalid_signature_is_rejected(self):
        with patch("notifications.webhook_views.verify_resend_webhook", side_effect=ResendWebhookVerificationError("invalid")):
            r = self.client.post(self.url, data=b'{}', content_type="application/json",
                                 HTTP_SVIX_ID="msg_bad", HTTP_SVIX_TIMESTAMP="1", HTTP_SVIX_SIGNATURE="v1,bad")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(EmailWebhookEvent.objects.filter(event_id="msg_bad").exists())

    def test_missing_signature_headers_are_rejected(self):
        response = self.client.post(
            self.url,
            data=b"{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_utf8_is_rejected_before_sdk_verification(self):
        with patch("notifications.webhook_security._load_resend") as load_resend:
            with self.assertRaises(ResendWebhookVerificationError):
                verify_resend_webhook(
                    raw_body=b"\xff",
                    svix_id="msg_invalid_utf8",
                    svix_timestamp="1",
                    svix_signature="v1,test",
                )
        load_resend.assert_not_called()

    def test_missing_server_config_returns_503(self):
        with patch("notifications.webhook_views.verify_resend_webhook", side_effect=ResendWebhookConfigurationError("missing")):
            r = self.client.post(self.url, data=b'{}', content_type="application/json",
                                 HTTP_SVIX_ID="msg_cfg", HTTP_SVIX_TIMESTAMP="1", HTTP_SVIX_SIGNATURE="v1,x")
        self.assertEqual(r.status_code, 503)

    def test_missing_email_id_is_400(self):
        payload = {"type": "email.bounced", "created_at": "2026-09-13T12:00:00Z", "data": {}}
        r = self.post_verified("msg_missing", payload)
        self.assertEqual(r.status_code, 400)

    def test_malformed_verified_payload_types_are_400(self):
        invalid_payloads = (
            [],
            {"type": 123, "data": {}},
            {"type": "email.opened", "data": []},
            {"type": "email.opened", "data": None},
        )
        for index, payload in enumerate(invalid_payloads):
            event_id = f"msg_malformed_verified_{index}"
            with self.subTest(payload=payload):
                response = self.post_verified(event_id, payload)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(
                    EmailWebhookEvent.objects.filter(event_id=event_id).exists()
                )

    def test_invalid_provider_message_ids_are_400_without_audit_rows(self):
        private_value = "private-provider-id\nsecret"
        invalid_values = (
            None,
            123,
            "",
            "   ",
            " id",
            "id ",
            "id value",
            "id  value",
            private_value,
            "x" * (PROVIDER_MESSAGE_ID_MAX_LENGTH + 1),
        )

        for index, provider_message_id in enumerate(invalid_values):
            with self.subTest(value_type=type(provider_message_id).__name__):
                payload = self.payload()
                payload["data"]["email_id"] = provider_message_id
                event_id = f"msg_invalid_provider_id_{index}"

                response = self.post_verified(event_id, payload)

                self.assertEqual(response.status_code, 400)
                self.assertFalse(
                    EmailWebhookEvent.objects.filter(event_id=event_id).exists()
                )

        with self.assertRaises(ResendWebhookPayloadError) as context:
            payload = self.payload()
            payload["data"]["email_id"] = private_value
            process_resend_webhook(
                event_id="msg_private_invalid_provider_id",
                payload=payload,
            )
        self.assertNotIn(private_value, str(context.exception))

    def _assert_invalid_tracked_created_at(self, event_id, payload):
        baseline = datetime(2026, 9, 13, 11, 0, tzinfo=dt_timezone.utc)
        self.delivery.provider_status = EmailDelivery.ProviderStatus.SENT
        self.delivery.provider_status_at = baseline
        self.delivery.save(update_fields=["provider_status", "provider_status_at"])

        response = self.post_verified(event_id, payload)

        self.assertEqual(response.status_code, 400)
        self.delivery.refresh_from_db()
        self.assertEqual(
            self.delivery.provider_status,
            EmailDelivery.ProviderStatus.SENT,
        )
        self.assertEqual(self.delivery.provider_status_at, baseline)
        self.assertFalse(EmailWebhookEvent.objects.filter(event_id=event_id).exists())

    def test_tracked_event_missing_created_at_is_rejected_without_side_effects(self):
        payload = self.payload("email.bounced")
        payload.pop("created_at")

        self._assert_invalid_tracked_created_at("msg_missing_time", payload)

    def test_tracked_event_blank_created_at_is_rejected_without_side_effects(self):
        self._assert_invalid_tracked_created_at(
            "msg_blank_time",
            self.payload("email.bounced", created_at="   "),
        )

    def test_tracked_event_malformed_created_at_is_rejected_without_side_effects(self):
        payload = self.payload("email.bounced", created_at="not-a-timestamp")

        self._assert_invalid_tracked_created_at("msg_bad_time", payload)

        with self.assertRaises(ResendWebhookPayloadError):
            process_resend_webhook(event_id="msg_bad_time_service", payload=payload)

    def test_valid_naive_timestamp_is_treated_as_utc(self):
        response = self.post_verified(
            "msg_naive_time",
            self.payload("email.delivered", created_at="2026-09-13T12:00:00"),
        )

        self.assertEqual(response.status_code, 200)
        self.delivery.refresh_from_db()
        self.assertEqual(
            self.delivery.provider_status_at,
            datetime(2026, 9, 13, 12, 0, tzinfo=dt_timezone.utc),
        )

    def test_untracked_event_keeps_permissive_timestamp_behavior(self):
        payload = self.payload("email.opened", created_at="not-a-timestamp")

        response = self.post_verified("msg_untracked", payload)

        self.assertEqual(response.status_code, 200)
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.provider_status, "")
        self.assertIsNone(self.delivery.provider_status_at)
        event = EmailWebhookEvent.objects.get(event_id="msg_untracked")
        self.assertEqual(
            event.processing_result,
            EmailWebhookEvent.ProcessingResult.IGNORED,
        )
        self.assertIsNotNone(event.event_created_at)

    def test_out_of_order_event_does_not_regress(self):
        newer = datetime(2026, 9, 13, 12, 5, tzinfo=dt_timezone.utc)
        older = newer - timedelta(minutes=5)
        self.post_verified("msg_new", self.payload("email.delivered", newer.isoformat().replace("+00:00", "Z")))
        self.post_verified("msg_old", self.payload("email.delivery_delayed", older.isoformat().replace("+00:00", "Z")))
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.provider_status, EmailDelivery.ProviderStatus.DELIVERED)
        self.assertEqual(self.delivery.provider_status_at, newer)

    def test_equal_timestamp_does_not_regress_delivered_to_delayed(self):
        created_at = "2026-09-13T12:05:00Z"
        self.assertEqual(
            self.post_verified(
                "msg_equal_delivered",
                self.payload("email.delivered", created_at),
            ).status_code,
            200,
        )
        self.assertEqual(
            self.post_verified(
                "msg_equal_delayed",
                self.payload("email.delivery_delayed", created_at),
            ).status_code,
            200,
        )

        self.delivery.refresh_from_db()
        self.assertEqual(
            self.delivery.provider_status,
            EmailDelivery.ProviderStatus.DELIVERED,
        )

    def test_later_timestamp_preserves_legitimate_lower_precedence_update(self):
        self.post_verified(
            "msg_earlier_delivered",
            self.payload("email.delivered", "2026-09-13T12:05:00Z"),
        )
        self.post_verified(
            "msg_later_delayed",
            self.payload("email.delivery_delayed", "2026-09-13T12:06:00Z"),
        )

        self.delivery.refresh_from_db()
        self.assertEqual(
            self.delivery.provider_status,
            EmailDelivery.ProviderStatus.DELAYED,
        )

    def test_unmatched_can_be_reconciled_later(self):
        unknown_id = "email_race_123"
        r = self.post_verified("msg_race", self.payload("email.bounced", email_id=unknown_id))
        self.assertEqual(r.status_code, 200)
        event = EmailWebhookEvent.objects.get(event_id="msg_race")
        self.assertEqual(event.processing_result, EmailWebhookEvent.ProcessingResult.UNMATCHED)
        late = EmailDelivery.objects.create(
            provider="resend", idempotency_key="dertderman/test-stage8-late",
            recipient_hash="b" * 64, status=EmailDelivery.Status.SENT,
            provider_message_id=unknown_id, attempt_count=1,
        )
        self.assertEqual(reconcile_unmatched_resend_events(unknown_id), 1)
        event.refresh_from_db(); late.refresh_from_db()
        self.assertEqual(event.delivery_id, late.pk)
        self.assertEqual(late.provider_status, EmailDelivery.ProviderStatus.BOUNCED)

    def test_reconciliation_uses_equal_timestamp_precedence_and_is_idempotent(self):
        unknown_id = "email_equal_timestamp_reconciliation"
        created_at = "2026-09-13T12:00:00Z"
        self.post_verified(
            "msg_reconcile_delivered",
            self.payload("email.delivered", created_at, unknown_id),
        )
        self.post_verified(
            "msg_reconcile_delayed",
            self.payload("email.delivery_delayed", created_at, unknown_id),
        )
        late = EmailDelivery.objects.create(
            provider="resend",
            idempotency_key="dertderman/test-stage8-equal-reconciliation",
            recipient_hash="b" * 64,
            status=EmailDelivery.Status.SENT,
            provider_message_id=unknown_id,
            attempt_count=1,
        )

        self.assertEqual(reconcile_unmatched_resend_events(unknown_id), 2)
        self.assertEqual(reconcile_unmatched_resend_events(unknown_id), 0)
        late.refresh_from_db()
        self.assertEqual(
            late.provider_status,
            EmailDelivery.ProviderStatus.DELIVERED,
        )
        self.assertFalse(
            EmailWebhookEvent.objects.filter(
                provider_message_id=unknown_id,
                processing_result=EmailWebhookEvent.ProcessingResult.UNMATCHED,
            ).exists()
        )

    def test_resend_webhook_does_not_match_other_provider_with_same_id(self):
        self.delivery.provider = "other-provider"
        self.delivery.save(update_fields=["provider"])

        response = self.post_verified("msg_wrong_provider", self.payload())

        self.assertEqual(response.status_code, 200)
        self.delivery.refresh_from_db()
        event = EmailWebhookEvent.objects.get(event_id="msg_wrong_provider")
        self.assertEqual(self.delivery.provider_status, "")
        self.assertEqual(
            event.processing_result,
            EmailWebhookEvent.ProcessingResult.UNMATCHED,
        )
        self.assertIsNone(event.delivery_id)

    def test_delivery_lookup_raises_integrity_alarm_instead_of_choosing_first(self):
        locked_deliveries = Mock()
        locked_deliveries.get.side_effect = EmailDelivery.MultipleObjectsReturned

        with patch(
            "notifications.webhook_service.EmailDelivery.objects.select_for_update",
            return_value=locked_deliveries,
        ):
            with self.assertRaises(ResendWebhookIntegrityError):
                process_resend_webhook(
                    event_id="msg_duplicate_delivery_integrity",
                    payload=self.payload(),
                )

        locked_deliveries.get.assert_called_once_with(
            provider="resend",
            provider_message_id=self.delivery.provider_message_id,
        )
        self.assertFalse(
            EmailWebhookEvent.objects.filter(
                event_id="msg_duplicate_delivery_integrity"
            ).exists()
        )

    def test_get_is_405(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    @override_settings(RESEND_WEBHOOK_MAX_BODY_BYTES=4)
    def test_oversized_body_is_413_before_verify(self):
        with patch("notifications.webhook_views.verify_resend_webhook") as verify:
            r = self.client.post(self.url, data=b'12345', content_type="application/json",
                                 HTTP_SVIX_ID="msg_large", HTTP_SVIX_TIMESTAMP="1", HTTP_SVIX_SIGNATURE="v1,x")
        self.assertEqual(r.status_code, 413)
        verify.assert_not_called()

    @override_settings(RESEND_WEBHOOK_MAX_BODY_BYTES=4)
    def test_oversized_actual_body_without_content_length_is_413(self):
        request = RequestFactory().post(
            self.url,
            data=b"12345",
            content_type="application/json",
        )
        request.META.pop("CONTENT_LENGTH", None)
        request.read = Mock(wraps=request.read)

        with patch("notifications.webhook_views.verify_resend_webhook") as verify:
            from .webhook_views import resend_webhook

            response = resend_webhook(request)

        self.assertEqual(response.status_code, 413)
        request.read.assert_called_once_with(5)
        verify.assert_not_called()

    @override_settings(RESEND_WEBHOOK_MAX_BODY_BYTES="invalid")
    def test_invalid_runtime_body_limit_returns_503_before_verify(self):
        with patch("notifications.webhook_views.verify_resend_webhook") as verify:
            response = self.client.post(
                self.url,
                data=b"{}",
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 503)
        verify.assert_not_called()
