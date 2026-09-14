import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import User

from .email_providers.resend import ResendDeliveryError
from .email_service import build_recipient_hash
from .models import EmailDelivery, EmailOutbox, Notification
from .outbox_service import (
    EmailPayload,
    OUTBOX_INVALID_RECIPE,
    OUTBOX_PROVIDER_MISMATCH,
    OUTBOX_UNSUPPORTED_TEMPLATE_VERSION,
    OutboxClaimLost,
    OutboxConfigurationError,
    OutboxPermanentItemError,
    _finalize_success,
    claim_email_outbox,
    mark_email_outbox_permanent_failure,
    release_email_outbox_claim,
    send_outbox_email,
)


@override_settings(
    EMAIL_SENDING_ENABLED=True,
    EMAIL_PROVIDER="resend",
    RESEND_API_KEY="re_test_only",
)
class EmailOutboxTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        resend_loader = patch("notifications.outbox_service._load_resend")
        resend_loader.start().return_value = object()
        self.addCleanup(resend_loader.stop)
        self.user = User.objects.create_user(
            username="outbox-user",
            email="outbox-user@example.com",
            password="StrongRiver#9284",
            user_type=User.UserType.USER,
            is_active=True,
            is_verified=True,
        )

    def make_outbox(self, **overrides):
        notification = overrides.pop("notification", None)
        if notification is None:
            notification = Notification.objects.create(
                recipient_user=self.user,
                recipient_role=Notification.Scope.USER,
                notification_type=Notification.Type.PUBLISHED,
                event_key=f"outbox:{uuid.uuid4()}",
                title="Outbox testi",
                message="Güvenli test içeriği.",
            )
        values = {
            "kind": EmailOutbox.Kind.NOTIFICATION,
            "recipient_user": self.user,
            "notification": notification,
            "recipient_hash": build_recipient_hash(self.user.email),
            "provider": "resend",
            "provider_idempotency_key": f"dertderman/email/{uuid.uuid4()}",
            "available_at": timezone.now() - timedelta(seconds=1),
        }
        values.update(overrides)
        return EmailOutbox.objects.create(**values)

    def payload(self, **overrides):
        values = {
            "recipient_email": self.user.email,
            "subject": "Outbox testi",
            "html_body": "<p>Outbox testi</p>",
            "text_body": "Outbox testi",
            "from_email": "DertDerman <info@dertderman.com>",
            "reply_to": "destek@dertderman.com",
        }
        values.update(overrides)
        return EmailPayload(**values)

    def claim_one(self, outbox):
        claims = claim_email_outbox(batch_size=1)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].outbox_id, outbox.pk)
        return claims[0]

    def test_recipe_constraint_rejects_incomplete_notification(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            EmailOutbox.objects.create(
                kind=EmailOutbox.Kind.NOTIFICATION,
                recipient_user=None,
                notification=None,
                recipient_hash="",
                provider_idempotency_key=f"dertderman/email/{uuid.uuid4()}",
                available_at=timezone.now(),
            )

    def test_processing_constraint_requires_complete_claim(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_outbox(status=EmailOutbox.Status.PROCESSING)

    def test_terminal_constraint_requires_completed_at(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_outbox(status=EmailOutbox.Status.DEAD)

    def test_provider_key_constraint_rejects_empty_values(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_outbox(provider="", provider_idempotency_key="")

    def test_competing_claim_does_not_claim_active_lease(self):
        outbox = self.make_outbox()
        first = claim_email_outbox(batch_size=1)
        second = claim_email_outbox(batch_size=1)

        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].outbox_id, outbox.pk)
        self.assertEqual(second, [])

    def test_expired_processing_lease_is_reclaimed(self):
        outbox = self.make_outbox()
        old_token = uuid.uuid4()
        now = timezone.now()
        EmailOutbox.objects.filter(pk=outbox.pk).update(
            status=EmailOutbox.Status.PROCESSING,
            claim_token=old_token,
            claimed_at=now - timedelta(minutes=3),
            lease_expires_at=now - timedelta(minutes=1),
        )

        claim = self.claim_one(outbox)

        self.assertNotEqual(claim.claim_token, old_token)

    @patch("notifications.outbox_service._send_with_provider")
    def test_old_claim_token_cannot_finalize_after_reclaim(self, provider_send):
        outbox = self.make_outbox()
        old_claim = self.claim_one(outbox)
        EmailOutbox.objects.filter(pk=outbox.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
        new_claim = self.claim_one(outbox)

        with self.assertRaises(OutboxClaimLost):
            send_outbox_email(
                outbox_id=outbox.pk,
                claim_token=old_claim.claim_token,
                payload=self.payload(),
            )

        self.assertNotEqual(old_claim.claim_token, new_claim.claim_token)
        provider_send.assert_not_called()

    def test_stale_worker_cannot_write_provider_success(self):
        outbox = self.make_outbox()
        old_claim = self.claim_one(outbox)
        EmailDelivery.objects.create(
            outbox=outbox,
            notification=outbox.notification,
            provider="resend",
            idempotency_key=outbox.provider_idempotency_key,
            recipient_hash=outbox.recipient_hash,
            status=EmailDelivery.Status.PENDING,
            attempt_count=1,
        )
        EmailOutbox.objects.filter(pk=outbox.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.claim_one(outbox)

        with self.assertRaises(OutboxClaimLost):
            _finalize_success(
                outbox_id=outbox.pk,
                claim_token=old_claim.claim_token,
                provider_message_id="stale-worker-message",
                now=timezone.now(),
            )

        delivery = EmailDelivery.objects.get(outbox=outbox)
        self.assertEqual(delivery.status, EmailDelivery.Status.PENDING)
        self.assertEqual(delivery.provider_message_id, "")

    @patch("notifications.outbox_service._send_with_provider")
    def test_deleted_claim_is_normalized_as_claim_lost(self, provider_send):
        from .management.commands.process_email_outbox import Command

        outbox = self.make_outbox()
        claim = self.claim_one(outbox)
        outbox.delete()

        with self.assertRaises(OutboxClaimLost):
            send_outbox_email(
                outbox_id=claim.outbox_id,
                claim_token=claim.claim_token,
                payload=self.payload(),
            )
        with self.assertRaises(OutboxClaimLost):
            _finalize_success(
                outbox_id=claim.outbox_id,
                claim_token=claim.claim_token,
                provider_message_id="deleted-outbox-message",
                now=timezone.now(),
            )

        # Management-command cleanup treats a concurrently deleted row as an
        # already-completed release and does not propagate the missing-row error.
        Command._release_claim(claim, "WORKER_INTERRUPTED")

        provider_send.assert_not_called()

    @patch("notifications.outbox_service._send_with_provider")
    def test_provider_call_is_outside_atomic_transaction(self, provider_send):
        outbox = self.make_outbox()
        claim = self.claim_one(outbox)

        def assert_no_transaction(_outbox, _payload):
            self.assertFalse(connection.in_atomic_block)
            return "provider-outside-transaction"

        provider_send.side_effect = assert_no_transaction
        send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            payload=self.payload(),
        )

    @patch("notifications.outbox_service._send_with_provider")
    def test_new_outbox_creates_and_sends_delivery(self, provider_send):
        provider_send.return_value = "provider-new-delivery"
        outbox = self.make_outbox()
        claim = self.claim_one(outbox)

        result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            payload=self.payload(),
        )

        outbox.refresh_from_db()
        delivery = EmailDelivery.objects.get(outbox=outbox)
        self.assertEqual(result.status, "sent")
        self.assertEqual(outbox.status, EmailOutbox.Status.SENT)
        self.assertIsNotNone(outbox.completed_at)
        self.assertIsNone(outbox.claim_token)
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)
        self.assertEqual(delivery.provider_message_id, "provider-new-delivery")
        self.assertEqual(outbox.attempt_count, 1)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertIsNotNone(outbox.first_attempt_at)
        self.assertAlmostEqual(
            (outbox.provider_retry_deadline_at - outbox.first_attempt_at).total_seconds(),
            23 * 60 * 60,
            delta=1,
        )

    @patch("notifications.outbox_service._send_with_provider")
    def test_sent_delivery_does_not_call_provider_again(self, provider_send):
        outbox = self.make_outbox()
        claim = self.claim_one(outbox)
        EmailDelivery.objects.create(
            outbox=outbox,
            notification=outbox.notification,
            provider="resend",
            idempotency_key=outbox.provider_idempotency_key,
            recipient_hash=outbox.recipient_hash,
            status=EmailDelivery.Status.SENT,
            provider_message_id="already-sent",
            attempt_count=1,
        )

        result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            payload=self.payload(),
        )

        self.assertEqual(result.status, "sent")
        self.assertEqual(result.provider_message_id, "already-sent")
        provider_send.assert_not_called()

    @patch("notifications.outbox_service._send_with_provider")
    def test_outbox_owned_pending_delivery_is_resumed(self, provider_send):
        provider_send.return_value = "resumed-message"
        outbox = self.make_outbox()
        claim = self.claim_one(outbox)
        delivery = EmailDelivery.objects.create(
            outbox=outbox,
            notification=outbox.notification,
            provider="resend",
            idempotency_key=outbox.provider_idempotency_key,
            recipient_hash=outbox.recipient_hash,
            status=EmailDelivery.Status.PENDING,
            attempt_count=1,
        )

        send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            payload=self.payload(),
        )

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)
        self.assertEqual(delivery.attempt_count, 2)

    @patch("notifications.outbox_service._send_with_provider")
    def test_legacy_pending_delivery_is_not_resumed(self, provider_send):
        outbox = self.make_outbox()
        claim = self.claim_one(outbox)
        EmailDelivery.objects.create(
            provider="resend",
            idempotency_key=outbox.provider_idempotency_key,
            recipient_hash=outbox.recipient_hash,
            status=EmailDelivery.Status.PENDING,
            attempt_count=1,
        )

        result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            payload=self.payload(),
        )

        outbox.refresh_from_db()
        self.assertEqual(result.status, "dead")
        self.assertEqual(outbox.status, EmailOutbox.Status.DEAD)
        self.assertEqual(outbox.last_error_code, "DELIVERY_OWNERSHIP_CONFLICT")
        provider_send.assert_not_called()

    @patch("notifications.outbox_service._send_with_provider")
    def test_changed_outbox_key_fails_delivery_invariant(self, provider_send):
        provider_send.side_effect = ResendDeliveryError(code="provider_network_error")
        outbox = self.make_outbox()
        first_claim = self.claim_one(outbox)
        send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=first_claim.claim_token,
            payload=self.payload(),
        )

        EmailOutbox.objects.filter(pk=outbox.pk).update(
            provider_idempotency_key=f"dertderman/email/{uuid.uuid4()}",
            available_at=timezone.now(),
        )
        second_claim = self.claim_one(outbox)
        result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=second_claim.claim_token,
            payload=self.payload(),
        )

        outbox.refresh_from_db()
        self.assertEqual(result.status, "dead")
        self.assertEqual(outbox.last_error_code, "DELIVERY_INVARIANT_MISMATCH")
        self.assertEqual(provider_send.call_count, 1)

    @patch("notifications.outbox_service._send_with_provider")
    def test_delivery_provider_mismatch_fails_closed(self, provider_send):
        outbox = self.make_outbox()
        claim = self.claim_one(outbox)
        EmailDelivery.objects.create(
            outbox=outbox,
            notification=outbox.notification,
            provider="other-provider",
            idempotency_key=outbox.provider_idempotency_key,
            recipient_hash=outbox.recipient_hash,
            status=EmailDelivery.Status.PENDING,
        )

        result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            payload=self.payload(),
        )

        outbox.refresh_from_db()
        self.assertEqual(result.status, "dead")
        self.assertEqual(outbox.last_error_code, "DELIVERY_INVARIANT_MISMATCH")
        provider_send.assert_not_called()

    @patch("notifications.outbox_service._send_with_provider")
    def test_delivery_recipient_hash_mismatch_fails_closed(self, provider_send):
        outbox = self.make_outbox()
        claim = self.claim_one(outbox)
        EmailDelivery.objects.create(
            outbox=outbox,
            notification=outbox.notification,
            provider=outbox.provider,
            idempotency_key=outbox.provider_idempotency_key,
            recipient_hash="0" * 64,
            status=EmailDelivery.Status.PENDING,
        )

        result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            payload=self.payload(),
        )

        outbox.refresh_from_db()
        self.assertEqual(result.status, "dead")
        self.assertEqual(outbox.last_error_code, "DELIVERY_INVARIANT_MISMATCH")
        provider_send.assert_not_called()

    @patch("notifications.email_providers.resend.ResendProvider.send")
    def test_retry_reuses_exact_provider_idempotency_key(self, provider_send):
        provider_send.side_effect = [
            ResendDeliveryError(code="provider_timeout"),
            "provider-after-retry",
        ]
        outbox = self.make_outbox()
        first_claim = self.claim_one(outbox)
        first = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=first_claim.claim_token,
            payload=self.payload(),
        )
        self.assertEqual(first.status, "retry")

        EmailOutbox.objects.filter(pk=outbox.pk).update(available_at=timezone.now())
        second_claim = self.claim_one(outbox)
        second = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=second_claim.claim_token,
            payload=self.payload(),
        )

        self.assertEqual(second.status, "sent")
        keys = [call.kwargs["idempotency_key"] for call in provider_send.call_args_list]
        self.assertEqual(keys, [outbox.provider_idempotency_key] * 2)

    @patch("notifications.outbox_service._send_with_provider")
    def test_payload_hash_mismatch_is_dead_without_second_send(self, provider_send):
        provider_send.side_effect = ResendDeliveryError(code="provider_network_error")
        outbox = self.make_outbox()
        first_claim = self.claim_one(outbox)
        send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=first_claim.claim_token,
            payload=self.payload(),
        )

        EmailOutbox.objects.filter(pk=outbox.pk).update(available_at=timezone.now())
        second_claim = self.claim_one(outbox)
        result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=second_claim.claim_token,
            payload=self.payload(subject="Changed subject"),
        )

        outbox.refresh_from_db()
        self.assertEqual(result.status, "dead")
        self.assertEqual(outbox.last_error_code, "PAYLOAD_HASH_MISMATCH")
        self.assertEqual(provider_send.call_count, 1)

    @patch("notifications.outbox_service._send_with_provider")
    def test_transient_error_moves_item_to_retry(self, provider_send):
        provider_send.side_effect = ResendDeliveryError(
            code="provider_rate_limited",
            retryable=True,
            outcome_unknown=False,
            retry_after_seconds=10,
        )
        outbox = self.make_outbox()
        claim = self.claim_one(outbox)
        before_send = timezone.now()

        result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            payload=self.payload(),
        )

        outbox.refresh_from_db()
        self.assertEqual(result.status, "retry")
        self.assertEqual(outbox.status, EmailOutbox.Status.RETRY)
        self.assertIsNone(outbox.claim_token)
        self.assertEqual(outbox.last_error_code, "provider_rate_limited")
        self.assertGreaterEqual(
            outbox.available_at,
            before_send + timedelta(seconds=10),
        )
        self.assertLess(
            outbox.available_at,
            before_send + timedelta(seconds=11),
        )

    @patch("notifications.outbox_service._send_with_provider")
    def test_provider_server_error_moves_item_to_retry(self, provider_send):
        provider_send.side_effect = ResendDeliveryError(
            code="provider_server_error",
            retryable=True,
            outcome_unknown=True,
        )
        outbox = self.make_outbox()
        claim = self.claim_one(outbox)

        result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            payload=self.payload(),
        )

        outbox.refresh_from_db()
        self.assertEqual(result.status, "retry")
        self.assertEqual(outbox.status, EmailOutbox.Status.RETRY)
        self.assertEqual(outbox.last_error_code, "provider_server_error")

    @patch("notifications.outbox_service._send_with_provider")
    def test_permanent_error_moves_item_to_dead(self, provider_send):
        provider_send.side_effect = ResendDeliveryError(
            code="provider_invalid_request",
            retryable=False,
            outcome_unknown=False,
        )
        outbox = self.make_outbox()
        claim = self.claim_one(outbox)

        result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            payload=self.payload(),
        )

        outbox.refresh_from_db()
        self.assertEqual(result.status, "dead")
        self.assertEqual(outbox.status, EmailOutbox.Status.DEAD)
        self.assertIsNotNone(outbox.completed_at)
        self.assertIsNone(outbox.claim_token)
        self.assertEqual(outbox.last_error_code, "provider_invalid_request")
        self.assertEqual(claim_email_outbox(batch_size=1), [])
        self.assertEqual(provider_send.call_count, 1)

    @patch(
        "notifications.management.commands.process_email_outbox."
        "validate_worker_configuration"
    )
    @patch(
        "notifications.management.commands.process_email_outbox."
        "render_outbox_email"
    )
    @patch("notifications.outbox_service._send_with_provider")
    def test_global_authentication_failure_stops_worker_without_dead_lettering(
        self,
        provider_send,
        render,
        _validate,
    ):
        provider_send.side_effect = ResendDeliveryError(
            code="provider_authentication",
            retryable=False,
            outcome_unknown=False,
            global_problem=True,
        )
        render.return_value = self.payload()
        outbox = self.make_outbox()

        with self.assertRaises(CommandError):
            call_command(
                "process_email_outbox",
                once=True,
                batch_size=1,
                poll_seconds=0.1,
            )

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.RETRY)
        self.assertNotEqual(outbox.status, EmailOutbox.Status.DEAD)
        self.assertEqual(outbox.attempt_count, 0)
        self.assertIsNone(outbox.first_attempt_at)
        self.assertIsNone(outbox.provider_retry_deadline_at)
        self.assertEqual(outbox.last_error_code, "WORKER_CONFIGURATION")
        self.assertIsNone(outbox.claim_token)
        self.assertEqual(provider_send.call_count, 1)
        self.assertEqual(outbox.delivery.status, EmailDelivery.Status.PENDING)
        self.assertEqual(outbox.delivery.attempt_count, 1)

    @patch(
        "notifications.management.commands.process_email_outbox."
        "validate_worker_configuration"
    )
    @patch(
        "notifications.management.commands.process_email_outbox."
        "render_outbox_email"
    )
    @patch("notifications.outbox_service._send_with_provider")
    def test_repeated_global_auth_failures_do_not_exhaust_retry_budget(
        self,
        provider_send,
        render,
        _validate,
    ):
        provider_send.side_effect = ResendDeliveryError(
            code="provider_authentication",
            retryable=False,
            outcome_unknown=False,
            global_problem=True,
        )
        render.return_value = self.payload()
        outbox = self.make_outbox(max_attempts=2)

        for _ in range(3):
            EmailOutbox.objects.filter(pk=outbox.pk).update(
                available_at=timezone.now() - timedelta(seconds=1)
            )
            with self.assertRaises(CommandError):
                call_command(
                    "process_email_outbox",
                    once=True,
                    batch_size=1,
                    poll_seconds=0.1,
                )

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.RETRY)
        self.assertEqual(outbox.attempt_count, 0)
        self.assertIsNone(outbox.first_attempt_at)
        self.assertIsNone(outbox.provider_retry_deadline_at)
        self.assertIsNone(outbox.completed_at)
        self.assertEqual(outbox.delivery.attempt_count, 3)

    @patch(
        "notifications.management.commands.process_email_outbox."
        "validate_worker_configuration"
    )
    @patch(
        "notifications.management.commands.process_email_outbox."
        "render_outbox_email"
    )
    @patch("notifications.outbox_service._send_with_provider")
    def test_item_sends_after_global_authentication_is_fixed(
        self,
        provider_send,
        render,
        _validate,
    ):
        provider_send.side_effect = [
            ResendDeliveryError(
                code="provider_authentication",
                retryable=False,
                outcome_unknown=False,
                global_problem=True,
            ),
            "provider-after-config-fix",
        ]
        render.return_value = self.payload()
        outbox = self.make_outbox(max_attempts=1)

        with self.assertRaises(CommandError):
            call_command("process_email_outbox", once=True, batch_size=1)
        EmailOutbox.objects.filter(pk=outbox.pk).update(
            available_at=timezone.now() - timedelta(seconds=1)
        )
        call_command("process_email_outbox", once=True, batch_size=1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.SENT)
        self.assertEqual(outbox.attempt_count, 1)
        self.assertEqual(outbox.delivery.attempt_count, 2)
        self.assertEqual(
            outbox.delivery.provider_message_id,
            "provider-after-config-fix",
        )

    @patch("notifications.outbox_service._send_with_provider")
    def test_global_auth_rollback_preserves_prior_retry_window(self, provider_send):
        provider_send.side_effect = [
            ResendDeliveryError(
                code="provider_timeout",
                retryable=True,
                outcome_unknown=True,
            ),
            ResendDeliveryError(
                code="provider_authentication",
                retryable=False,
                outcome_unknown=False,
                global_problem=True,
            ),
        ]
        outbox = self.make_outbox(max_attempts=3)
        first_claim = self.claim_one(outbox)
        first_result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=first_claim.claim_token,
            payload=self.payload(),
        )
        self.assertEqual(first_result.status, "retry")
        outbox.refresh_from_db()
        first_attempt_at = outbox.first_attempt_at
        retry_deadline = outbox.provider_retry_deadline_at

        EmailOutbox.objects.filter(pk=outbox.pk).update(
            available_at=timezone.now() - timedelta(seconds=1)
        )
        second_claim = self.claim_one(outbox)
        with self.assertRaises(OutboxConfigurationError):
            send_outbox_email(
                outbox_id=outbox.pk,
                claim_token=second_claim.claim_token,
                payload=self.payload(),
            )

        outbox.refresh_from_db()
        self.assertEqual(outbox.attempt_count, 1)
        self.assertEqual(outbox.first_attempt_at, first_attempt_at)
        self.assertEqual(outbox.provider_retry_deadline_at, retry_deadline)
        self.assertEqual(outbox.delivery.attempt_count, 2)

    @patch("notifications.outbox_service._send_with_provider")
    def test_max_attempts_moves_item_to_dead(self, provider_send):
        provider_send.side_effect = ResendDeliveryError(code="server_error")
        outbox = self.make_outbox(max_attempts=1)
        claim = self.claim_one(outbox)

        result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            payload=self.payload(),
        )

        outbox.refresh_from_db()
        self.assertEqual(result.status, "dead")
        self.assertEqual(outbox.last_error_code, "MAX_ATTEMPTS_EXCEEDED")

    @patch("notifications.outbox_service._send_with_provider")
    def test_expired_retry_deadline_is_dead_without_provider(self, provider_send):
        outbox = self.make_outbox(
            attempt_count=1,
            first_attempt_at=timezone.now() - timedelta(hours=24),
            provider_retry_deadline_at=timezone.now() - timedelta(hours=1),
        )
        claim = self.claim_one(outbox)

        result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            payload=self.payload(),
        )

        outbox.refresh_from_db()
        self.assertEqual(result.status, "dead")
        self.assertEqual(
            outbox.last_error_code,
            "PROVIDER_RETRY_DEADLINE_EXCEEDED",
        )
        provider_send.assert_not_called()

    @override_settings(EMAIL_SENDING_ENABLED=False)
    def test_command_fails_fast_without_consuming_items(self):
        outbox = self.make_outbox()

        with self.assertRaises(CommandError):
            call_command("process_email_outbox", once=True)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.PENDING)
        self.assertEqual(outbox.attempt_count, 0)

    @patch("notifications.outbox_service._send_with_provider")
    def test_dispatch_configuration_failure_does_not_consume_attempt(
        self,
        provider_send,
    ):
        outbox = self.make_outbox()
        claim = self.claim_one(outbox)

        with self.settings(RESEND_API_KEY=""):
            with self.assertRaises(OutboxConfigurationError):
                send_outbox_email(
                    outbox_id=outbox.pk,
                    claim_token=claim.claim_token,
                    payload=self.payload(),
                )

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.PROCESSING)
        self.assertEqual(outbox.attempt_count, 0)
        self.assertIsNone(outbox.first_attempt_at)
        self.assertIsNone(outbox.provider_retry_deadline_at)
        self.assertFalse(EmailDelivery.objects.filter(outbox=outbox).exists())
        provider_send.assert_not_called()

        release_email_outbox_claim(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            code="WORKER_CONFIGURATION",
        )
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.RETRY)
        self.assertNotEqual(outbox.status, EmailOutbox.Status.DEAD)
        self.assertIsNone(outbox.claim_token)

    @patch("notifications.outbox_service._send_with_provider")
    def test_provider_configuration_failure_rolls_back_prepared_attempt(
        self,
        provider_send,
    ):
        provider_send.side_effect = OutboxConfigurationError(
            "Provider client configuration failed."
        )
        outbox = self.make_outbox()
        claim = self.claim_one(outbox)

        with self.assertRaises(OutboxConfigurationError):
            send_outbox_email(
                outbox_id=outbox.pk,
                claim_token=claim.claim_token,
                payload=self.payload(),
            )

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.PROCESSING)
        self.assertEqual(outbox.attempt_count, 0)
        self.assertIsNone(outbox.first_attempt_at)
        self.assertIsNone(outbox.provider_retry_deadline_at)
        self.assertEqual(outbox.delivery.attempt_count, 1)

    @patch(
        "notifications.management.commands.process_email_outbox."
        "validate_worker_configuration"
    )
    @patch(
        "notifications.management.commands.process_email_outbox."
        "render_outbox_email"
    )
    @patch("notifications.outbox_service._send_with_provider")
    def test_command_once_processes_a_rendered_item(
        self,
        provider_send,
        render,
        _validate,
    ):
        provider_send.return_value = "command-message"
        render.return_value = self.payload()
        outbox = self.make_outbox()

        call_command(
            "process_email_outbox",
            once=True,
            batch_size=5,
            poll_seconds=0.1,
        )

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.SENT)
        self.assertEqual(outbox.delivery.provider_message_id, "command-message")

    @patch(
        "notifications.management.commands.process_email_outbox."
        "validate_worker_configuration"
    )
    @patch(
        "notifications.management.commands.process_email_outbox."
        "render_outbox_email"
    )
    @patch("notifications.outbox_service._send_with_provider")
    def test_command_isolates_an_unexpected_item_error(
        self,
        provider_send,
        render,
        _validate,
    ):
        first = self.make_outbox()
        second = self.make_outbox()
        first_id = first.pk

        def render_item(item):
            if item.pk == first_id:
                raise RuntimeError("sensitive renderer detail")
            return self.payload()

        render.side_effect = render_item
        provider_send.return_value = "isolated-message"

        call_command(
            "process_email_outbox",
            once=True,
            batch_size=5,
            poll_seconds=0.1,
        )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, EmailOutbox.Status.RETRY)
        self.assertEqual(first.attempt_count, 0)
        self.assertEqual(second.status, EmailOutbox.Status.SENT)

    @patch(
        "notifications.management.commands.process_email_outbox."
        "validate_worker_configuration"
    )
    @patch(
        "notifications.management.commands.process_email_outbox."
        "render_outbox_email"
    )
    @patch("notifications.outbox_service._send_with_provider")
    def test_command_continues_when_claimed_outbox_is_deleted(
        self,
        provider_send,
        render,
        _validate,
    ):
        deleted = self.make_outbox()
        survivor = self.make_outbox()
        deleted_id = deleted.pk

        def render_and_delete(item):
            if item.pk == deleted_id:
                item.delete()
            return self.payload()

        render.side_effect = render_and_delete
        provider_send.return_value = "surviving-message"

        call_command(
            "process_email_outbox",
            once=True,
            batch_size=5,
            poll_seconds=0.1,
        )

        self.assertFalse(EmailOutbox.objects.filter(pk=deleted_id).exists())
        survivor.refresh_from_db()
        self.assertEqual(survivor.status, EmailOutbox.Status.SENT)
        self.assertEqual(provider_send.call_count, 1)

    @patch("notifications.outbox_service._send_with_provider")
    def test_command_dead_letters_poison_then_sends_valid_item(self, provider_send):
        provider_send.return_value = "valid-after-poison"
        poison = self.make_outbox(template_version=2)
        valid = self.make_outbox()

        call_command("process_email_outbox", once=True, batch_size=5)

        poison.refresh_from_db()
        valid.refresh_from_db()
        self.assertEqual(poison.status, EmailOutbox.Status.DEAD)
        self.assertEqual(
            poison.last_error_code,
            OUTBOX_UNSUPPORTED_TEMPLATE_VERSION,
        )
        self.assertEqual(poison.attempt_count, 0)
        self.assertIsNone(poison.first_attempt_at)
        self.assertIsNone(poison.provider_retry_deadline_at)
        self.assertEqual(poison.payload_hash, "")
        self.assertFalse(EmailDelivery.objects.filter(outbox=poison).exists())
        self.assertEqual(valid.status, EmailOutbox.Status.SENT)
        self.assertEqual(provider_send.call_count, 1)

    @patch("notifications.outbox_service._send_with_provider")
    def test_command_isolates_poison_between_valid_items(self, provider_send):
        provider_send.side_effect = ["valid-before-poison", "valid-after-poison"]
        first = self.make_outbox()
        poison = self.make_outbox(template_version=2)
        last = self.make_outbox()

        call_command("process_email_outbox", once=True, batch_size=5)

        first.refresh_from_db()
        poison.refresh_from_db()
        last.refresh_from_db()
        self.assertEqual(first.status, EmailOutbox.Status.SENT)
        self.assertEqual(poison.status, EmailOutbox.Status.DEAD)
        self.assertEqual(last.status, EmailOutbox.Status.SENT)
        self.assertEqual(provider_send.call_count, 2)

    @patch("notifications.outbox_service._send_with_provider")
    def test_stored_provider_mismatch_isolated_from_valid_item(self, provider_send):
        provider_send.return_value = "valid-provider-message"
        poison = self.make_outbox(provider="corrupt-provider")
        valid = self.make_outbox()

        call_command("process_email_outbox", once=True, batch_size=5)

        poison.refresh_from_db()
        valid.refresh_from_db()
        self.assertEqual(poison.status, EmailOutbox.Status.DEAD)
        self.assertEqual(poison.last_error_code, OUTBOX_PROVIDER_MISMATCH)
        self.assertEqual(poison.attempt_count, 0)
        self.assertIsNone(poison.first_attempt_at)
        self.assertIsNone(poison.provider_retry_deadline_at)
        self.assertEqual(poison.payload_hash, "")
        self.assertFalse(EmailDelivery.objects.filter(outbox=poison).exists())
        self.assertEqual(valid.status, EmailOutbox.Status.SENT)
        self.assertEqual(provider_send.call_count, 1)

    def test_stale_claim_cannot_dead_letter_poison_item(self):
        outbox = self.make_outbox()
        old_claim = self.claim_one(outbox)
        EmailOutbox.objects.filter(pk=outbox.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
        new_claim = self.claim_one(outbox)

        with self.assertRaises(OutboxClaimLost):
            mark_email_outbox_permanent_failure(
                outbox_id=outbox.pk,
                claim_token=old_claim.claim_token,
                error_code=OUTBOX_INVALID_RECIPE,
            )

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.PROCESSING)
        self.assertEqual(outbox.claim_token, new_claim.claim_token)
        self.assertEqual(outbox.last_error_code, "")
        self.assertIsNone(outbox.completed_at)

    def test_permanent_finalizer_preserves_existing_delivery_audit(self):
        first_attempt_at = timezone.now() - timedelta(minutes=10)
        retry_deadline = first_attempt_at + timedelta(hours=23)
        outbox = self.make_outbox(
            payload_hash="a" * 64,
            attempt_count=2,
            first_attempt_at=first_attempt_at,
            provider_retry_deadline_at=retry_deadline,
        )
        delivery = EmailDelivery.objects.create(
            outbox=outbox,
            notification=outbox.notification,
            provider=outbox.provider,
            idempotency_key=outbox.provider_idempotency_key,
            recipient_hash=outbox.recipient_hash,
            status=EmailDelivery.Status.FAILED,
            attempt_count=2,
            last_error_type="provider_timeout",
        )
        claim = self.claim_one(outbox)

        mark_email_outbox_permanent_failure(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            error_code=OUTBOX_INVALID_RECIPE,
        )

        outbox.refresh_from_db()
        delivery.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.DEAD)
        self.assertEqual(outbox.attempt_count, 2)
        self.assertEqual(outbox.payload_hash, "a" * 64)
        self.assertEqual(outbox.first_attempt_at, first_attempt_at)
        self.assertEqual(outbox.provider_retry_deadline_at, retry_deadline)
        self.assertEqual(delivery.status, EmailDelivery.Status.FAILED)
        self.assertEqual(delivery.attempt_count, 2)
        self.assertEqual(delivery.last_error_type, "provider_timeout")

    @patch(
        "notifications.management.commands.process_email_outbox."
        "render_outbox_email"
    )
    @patch("notifications.outbox_service._send_with_provider")
    def test_permanent_failure_does_not_log_or_persist_raw_detail(
        self,
        provider_send,
        render,
    ):
        sensitive = "victim@example.com token=secret raw renderer failure"
        render.side_effect = OutboxPermanentItemError(sensitive)
        outbox = self.make_outbox()

        with self.assertLogs(
            "notifications.management.commands.process_email_outbox",
            level="WARNING",
        ) as captured:
            call_command("process_email_outbox", once=True, batch_size=1)

        outbox.refresh_from_db()
        log_output = "\n".join(captured.output)
        self.assertEqual(outbox.status, EmailOutbox.Status.DEAD)
        self.assertEqual(outbox.last_error_code, OUTBOX_INVALID_RECIPE)
        self.assertNotIn(sensitive, log_output)
        self.assertNotIn("victim@example.com", log_output)
        self.assertNotIn("secret", log_output)
        provider_send.assert_not_called()

    @override_settings(RESEND_API_KEY="")
    def test_missing_api_key_remains_global_and_does_not_poison_item(self):
        outbox = self.make_outbox()

        with self.assertRaises(CommandError):
            call_command("process_email_outbox", once=True)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.PENDING)
        self.assertEqual(outbox.attempt_count, 0)
        self.assertFalse(EmailDelivery.objects.filter(outbox=outbox).exists())

    @override_settings(EMAIL_PROVIDER="unsupported")
    def test_unsupported_global_provider_does_not_poison_item(self):
        outbox = self.make_outbox()

        with self.assertRaises(CommandError):
            call_command("process_email_outbox", once=True)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.PENDING)
        self.assertEqual(outbox.attempt_count, 0)
        self.assertFalse(EmailDelivery.objects.filter(outbox=outbox).exists())
