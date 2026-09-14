import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.template import TemplateDoesNotExist, TemplateSyntaxError
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import User

from .email_providers.resend import ResendDeliveryError
from .email_service import build_recipient_hash
from .models import EmailDelivery, EmailOutbox, Notification
from .outbox_service import (
    MAX_RENDER_FAILURES,
    OUTBOX_RENDER_RETRY_EXHAUSTED,
    OUTBOX_UNSUPPORTED_TEMPLATE_VERSION,
    EmailPayload,
    OutboxBusinessCancellation,
    OutboxClaimLost,
    OutboxConfigurationError,
    OutboxPermanentItemError,
    claim_email_outbox,
    record_email_outbox_render_failure,
    reset_email_outbox_render_failure_count,
)


@override_settings(
    EMAIL_SENDING_ENABLED=True,
    EMAIL_PROVIDER="resend",
    RESEND_API_KEY="re_test_only",
    RESEND_TIMEOUT_SECONDS=30,
    DEFAULT_FROM_EMAIL="DertDerman <info@dertderman.com>",
    EMAIL_REPLY_TO="destek@dertderman.com",
    SITE_BASE_URL="https://dertderman.com",
    IS_PRODUCTION=False,
)
class RenderRetryTests(TransactionTestCase):
    def setUp(self):
        resend_loader = patch("notifications.outbox_service._load_resend")
        resend_loader.start().return_value = object()
        self.addCleanup(resend_loader.stop)
        self.user = User.objects.create_user(
            username="render-retry-user",
            email="render-retry@example.com",
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
                event_key=f"render-retry:{uuid.uuid4()}",
                title="Render retry",
                message="Safe test content.",
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

    def payload(self):
        return EmailPayload(
            recipient_email=self.user.email,
            subject="Render retry",
            html_body="<p>Render retry</p>",
            text_body="Render retry",
            from_email="DertDerman <info@dertderman.com>",
            reply_to="destek@dertderman.com",
        )

    def claim_one(self, outbox, *, now=None):
        claims = claim_email_outbox(batch_size=1, now=now)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].outbox_id, outbox.pk)
        return claims[0]

    def make_claimable(self, outbox, now):
        EmailOutbox.objects.filter(pk=outbox.pk).update(
            available_at=now - timedelta(seconds=1)
        )

    def test_model_default_is_zero_and_non_null(self):
        outbox = self.make_outbox()
        field = EmailOutbox._meta.get_field("render_failure_count")

        self.assertEqual(outbox.render_failure_count, 0)
        self.assertEqual(field.default, 0)
        self.assertFalse(field.null)

    def test_fresh_render_failure_retries_without_provider_state(self):
        now = timezone.now()
        outbox = self.make_outbox()
        claim = self.claim_one(outbox, now=now)

        result = record_email_outbox_render_failure(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            now=now,
        )

        outbox.refresh_from_db()
        self.assertEqual(result, "retry")
        self.assertEqual(outbox.status, EmailOutbox.Status.RETRY)
        self.assertEqual(outbox.render_failure_count, 1)
        self.assertEqual(outbox.available_at, now + timedelta(seconds=30))
        self.assertEqual(outbox.last_error_code, "WORKER_UNEXPECTED_ERROR")
        self.assertEqual(outbox.attempt_count, 0)
        self.assertEqual(outbox.payload_hash, "")
        self.assertIsNone(outbox.first_attempt_at)
        self.assertIsNone(outbox.provider_retry_deadline_at)
        self.assertIsNone(outbox.completed_at)
        self.assertIsNone(outbox.claim_token)
        self.assertFalse(EmailDelivery.objects.filter(outbox=outbox).exists())

    def test_consecutive_render_failures_have_deterministic_backoff(self):
        outbox = self.make_outbox()
        base = timezone.now()

        for count, delay_seconds in ((1, 30), (2, 60), (3, 120), (4, 240)):
            now = base + timedelta(minutes=count * 10)
            self.make_claimable(outbox, now)
            claim = self.claim_one(outbox, now=now)
            result = record_email_outbox_render_failure(
                outbox_id=outbox.pk,
                claim_token=claim.claim_token,
                now=now,
            )
            outbox.refresh_from_db()

            self.assertEqual(result, "retry")
            self.assertEqual(outbox.status, EmailOutbox.Status.RETRY)
            self.assertEqual(outbox.render_failure_count, count)
            self.assertEqual(
                outbox.available_at,
                now + timedelta(seconds=delay_seconds),
            )
            self.assertEqual(outbox.attempt_count, 0)

    def test_fifth_render_failure_is_terminal(self):
        now = timezone.now()
        outbox = self.make_outbox(render_failure_count=4)
        claim = self.claim_one(outbox, now=now)

        result = record_email_outbox_render_failure(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            now=now,
        )

        outbox.refresh_from_db()
        self.assertEqual(MAX_RENDER_FAILURES, 5)
        self.assertEqual(result, "dead")
        self.assertEqual(outbox.status, EmailOutbox.Status.DEAD)
        self.assertEqual(outbox.render_failure_count, 5)
        self.assertEqual(
            outbox.last_error_code,
            OUTBOX_RENDER_RETRY_EXHAUSTED,
        )
        self.assertEqual(outbox.completed_at, now)
        self.assertIsNone(outbox.claim_token)
        self.assertIsNone(outbox.claimed_at)
        self.assertIsNone(outbox.lease_expires_at)
        self.assertEqual(outbox.attempt_count, 0)
        self.assertEqual(outbox.payload_hash, "")
        self.assertFalse(EmailDelivery.objects.filter(outbox=outbox).exists())

    @patch("notifications.management.commands.process_email_outbox.render_outbox_email")
    @patch("notifications.outbox_service._send_with_provider")
    def test_five_render_failures_never_call_provider(
        self,
        provider,
        render,
    ):
        render.side_effect = RuntimeError("private renderer detail")
        outbox = self.make_outbox()

        for expected_count in range(1, MAX_RENDER_FAILURES + 1):
            self.make_claimable(outbox, timezone.now())
            call_command("process_email_outbox", once=True, batch_size=1)
            outbox.refresh_from_db()
            self.assertEqual(outbox.render_failure_count, expected_count)
            self.assertEqual(outbox.attempt_count, 0)
            self.assertEqual(outbox.payload_hash, "")
            self.assertFalse(EmailDelivery.objects.filter(outbox=outbox).exists())

        self.assertEqual(outbox.status, EmailOutbox.Status.DEAD)
        provider.assert_not_called()

    @patch("notifications.management.commands.process_email_outbox.render_outbox_email")
    @patch("notifications.outbox_service._send_with_provider")
    def test_successful_render_resets_counter_before_provider_retry(
        self,
        provider,
        render,
    ):
        render.return_value = self.payload()
        provider.side_effect = ResendDeliveryError(
            code="provider_timeout",
            retryable=True,
            outcome_unknown=True,
        )
        outbox = self.make_outbox(render_failure_count=3)

        call_command("process_email_outbox", once=True, batch_size=1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.RETRY)
        self.assertEqual(outbox.render_failure_count, 0)
        self.assertEqual(outbox.attempt_count, 1)

    @patch("notifications.management.commands.process_email_outbox.render_outbox_email")
    @patch("notifications.outbox_service._send_with_provider")
    def test_failure_after_success_reset_restarts_at_one(self, provider, render):
        render.side_effect = [self.payload(), RuntimeError("render failed again")]
        provider.side_effect = ResendDeliveryError(
            code="provider_timeout",
            retryable=True,
            outcome_unknown=True,
        )
        outbox = self.make_outbox(render_failure_count=3)

        call_command("process_email_outbox", once=True, batch_size=1)
        self.make_claimable(outbox, timezone.now())
        call_command("process_email_outbox", once=True, batch_size=1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.RETRY)
        self.assertEqual(outbox.render_failure_count, 1)
        self.assertEqual(outbox.attempt_count, 1)
        self.assertEqual(outbox.delivery.attempt_count, 1)

    @patch("notifications.management.commands.process_email_outbox.render_outbox_email")
    def test_known_permanent_error_does_not_increment_counter(self, render):
        render.side_effect = OutboxPermanentItemError(
            OUTBOX_UNSUPPORTED_TEMPLATE_VERSION
        )
        outbox = self.make_outbox(render_failure_count=2)

        call_command("process_email_outbox", once=True, batch_size=1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.DEAD)
        self.assertEqual(outbox.render_failure_count, 2)
        self.assertEqual(
            outbox.last_error_code,
            OUTBOX_UNSUPPORTED_TEMPLATE_VERSION,
        )

    @patch("notifications.management.commands.process_email_outbox.render_outbox_email")
    def test_business_cancellation_does_not_increment_counter(self, render):
        render.side_effect = OutboxBusinessCancellation("NOTIFICATION_POLICY_CHANGED")
        outbox = self.make_outbox(render_failure_count=2)

        call_command("process_email_outbox", once=True, batch_size=1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.CANCELLED)
        self.assertEqual(outbox.render_failure_count, 2)
        self.assertEqual(outbox.last_error_code, "NOTIFICATION_POLICY_CHANGED")

    @patch("notifications.management.commands.process_email_outbox.render_outbox_email")
    def test_global_configuration_error_does_not_increment_counter(self, render):
        render.side_effect = OutboxConfigurationError("Safe global failure")
        outbox = self.make_outbox(render_failure_count=2)

        with self.assertRaises(CommandError):
            call_command("process_email_outbox", once=True, batch_size=1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.RETRY)
        self.assertEqual(outbox.render_failure_count, 2)
        self.assertEqual(outbox.last_error_code, "WORKER_CONFIGURATION")

    @patch("notifications.management.commands.process_email_outbox.render_outbox_email")
    def test_runtime_template_errors_do_not_increment_counter(self, render):
        for error in (
            TemplateDoesNotExist("private missing path"),
            TemplateSyntaxError("private template source"),
        ):
            with self.subTest(error=error.__class__.__name__):
                outbox = self.make_outbox(render_failure_count=2)
                render.side_effect = error
                with self.assertRaises(CommandError):
                    call_command("process_email_outbox", once=True, batch_size=1)
                outbox.refresh_from_db()
                self.assertEqual(outbox.status, EmailOutbox.Status.RETRY)
                self.assertEqual(outbox.render_failure_count, 2)
                self.assertEqual(outbox.last_error_code, "WORKER_CONFIGURATION")

    @patch("notifications.management.commands.process_email_outbox.send_outbox_email")
    @patch("notifications.management.commands.process_email_outbox.render_outbox_email")
    def test_generic_dispatch_error_does_not_increment_render_counter(
        self,
        render,
        dispatch,
    ):
        render.return_value = self.payload()
        dispatch.side_effect = RuntimeError("private dispatch detail")
        outbox = self.make_outbox(render_failure_count=2)

        call_command("process_email_outbox", once=True, batch_size=1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.RETRY)
        self.assertEqual(outbox.render_failure_count, 0)
        self.assertEqual(outbox.last_error_code, "WORKER_UNEXPECTED_ERROR")

    @patch("notifications.management.commands.process_email_outbox.render_outbox_email")
    @patch("notifications.outbox_service._send_with_provider")
    def test_provider_timeout_does_not_increment_render_counter(
        self,
        provider,
        render,
    ):
        render.return_value = self.payload()
        provider.side_effect = ResendDeliveryError(
            code="provider_timeout",
            retryable=True,
            outcome_unknown=True,
        )
        outbox = self.make_outbox()

        call_command("process_email_outbox", once=True, batch_size=1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.render_failure_count, 0)
        self.assertEqual(outbox.attempt_count, 1)
        self.assertEqual(outbox.delivery.attempt_count, 1)

    @patch("notifications.management.commands.process_email_outbox.render_outbox_email")
    @patch("notifications.outbox_service._send_with_provider")
    def test_provider_auth_failure_does_not_increment_render_counter(
        self,
        provider,
        render,
    ):
        render.return_value = self.payload()
        outbox = self.make_outbox()

        for status_code in (401, 403):
            with self.subTest(status_code=status_code):
                provider.side_effect = ResendDeliveryError(
                    code="provider_authentication",
                    retryable=False,
                    outcome_unknown=False,
                    global_problem=True,
                )
                self.make_claimable(outbox, timezone.now())
                with self.assertRaises(CommandError):
                    call_command("process_email_outbox", once=True, batch_size=1)
                outbox.refresh_from_db()
                self.assertEqual(outbox.render_failure_count, 0)
                self.assertEqual(outbox.attempt_count, 0)

    def test_stale_claim_cannot_record_render_failure(self):
        now = timezone.now()
        outbox = self.make_outbox(render_failure_count=2)
        old_claim = self.claim_one(outbox, now=now)
        EmailOutbox.objects.filter(pk=outbox.pk).update(
            lease_expires_at=now - timedelta(seconds=1)
        )
        new_claim = self.claim_one(outbox, now=now)

        with self.assertRaises(OutboxClaimLost):
            record_email_outbox_render_failure(
                outbox_id=outbox.pk,
                claim_token=old_claim.claim_token,
                now=now,
            )

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.PROCESSING)
        self.assertEqual(outbox.claim_token, new_claim.claim_token)
        self.assertEqual(outbox.render_failure_count, 2)

    def test_stale_claim_cannot_reset_render_failure_count(self):
        now = timezone.now()
        outbox = self.make_outbox(render_failure_count=3)
        old_claim = self.claim_one(outbox, now=now)
        EmailOutbox.objects.filter(pk=outbox.pk).update(
            lease_expires_at=now - timedelta(seconds=1)
        )
        new_claim = self.claim_one(outbox, now=now)

        with self.assertRaises(OutboxClaimLost):
            reset_email_outbox_render_failure_count(
                outbox_id=outbox.pk,
                claim_token=old_claim.claim_token,
                now=now,
            )

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.PROCESSING)
        self.assertEqual(outbox.claim_token, new_claim.claim_token)
        self.assertEqual(outbox.render_failure_count, 3)

    def test_render_failure_preserves_existing_provider_and_delivery_history(self):
        now = timezone.now()
        first_attempt_at = now - timedelta(hours=1)
        retry_deadline = now + timedelta(hours=22)
        payload_hash = "a" * 64
        outbox = self.make_outbox(
            attempt_count=2,
            first_attempt_at=first_attempt_at,
            provider_retry_deadline_at=retry_deadline,
            payload_hash=payload_hash,
        )
        delivery = EmailDelivery.objects.create(
            outbox=outbox,
            notification=outbox.notification,
            provider="resend",
            idempotency_key=outbox.provider_idempotency_key,
            recipient_hash=outbox.recipient_hash,
            status=EmailDelivery.Status.FAILED,
            attempt_count=2,
            provider_message_id="existing-provider-message",
            last_error_type="provider_timeout",
        )
        claim = self.claim_one(outbox, now=now)

        record_email_outbox_render_failure(
            outbox_id=outbox.pk,
            claim_token=claim.claim_token,
            now=now,
        )

        outbox.refresh_from_db()
        delivery.refresh_from_db()
        self.assertEqual(outbox.attempt_count, 2)
        self.assertEqual(outbox.first_attempt_at, first_attempt_at)
        self.assertEqual(outbox.provider_retry_deadline_at, retry_deadline)
        self.assertEqual(outbox.payload_hash, payload_hash)
        self.assertEqual(delivery.attempt_count, 2)
        self.assertEqual(delivery.provider_message_id, "existing-provider-message")
        self.assertEqual(delivery.last_error_type, "provider_timeout")

    @patch("notifications.management.commands.process_email_outbox.render_outbox_email")
    def test_generic_render_failure_does_not_log_or_persist_raw_detail(self, render):
        sensitive = "victim@example.com token=secret private-render-body"
        render.side_effect = RuntimeError(sensitive)
        outbox = self.make_outbox()

        with self.assertLogs(
            "notifications.management.commands.process_email_outbox",
            level="ERROR",
        ) as captured:
            call_command("process_email_outbox", once=True, batch_size=1)

        outbox.refresh_from_db()
        output = "\n".join(captured.output)
        self.assertNotIn(sensitive, output)
        self.assertNotIn("victim@example.com", output)
        self.assertNotIn("secret", output)
        self.assertEqual(outbox.last_error_code, "WORKER_UNEXPECTED_ERROR")

    @patch("notifications.management.commands.process_email_outbox.render_outbox_email")
    @patch("notifications.outbox_service._send_with_provider")
    def test_render_failure_does_not_block_following_valid_item(
        self,
        provider,
        render,
    ):
        failing = self.make_outbox()
        valid = self.make_outbox()

        def render_item(item):
            if item.pk == failing.pk:
                raise RuntimeError("private render failure")
            return self.payload()

        render.side_effect = render_item
        provider.return_value = "valid-after-render-failure"

        call_command("process_email_outbox", once=True, batch_size=5)

        failing.refresh_from_db()
        valid.refresh_from_db()
        self.assertEqual(failing.status, EmailOutbox.Status.RETRY)
        self.assertEqual(failing.render_failure_count, 1)
        self.assertEqual(valid.status, EmailOutbox.Status.SENT)
        self.assertEqual(provider.call_count, 1)

    @patch("notifications.management.commands.process_email_outbox.render_outbox_email")
    @patch("notifications.outbox_service._send_with_provider")
    def test_exhausted_render_item_does_not_stop_worker(
        self,
        provider,
        render,
    ):
        exhausted = self.make_outbox(render_failure_count=4)
        valid = self.make_outbox()

        def render_item(item):
            if item.pk == exhausted.pk:
                raise RuntimeError("private terminal render failure")
            return self.payload()

        render.side_effect = render_item
        provider.return_value = "valid-after-render-exhaustion"

        call_command("process_email_outbox", once=True, batch_size=5)

        exhausted.refresh_from_db()
        valid.refresh_from_db()
        self.assertEqual(exhausted.status, EmailOutbox.Status.DEAD)
        self.assertEqual(exhausted.render_failure_count, 5)
        self.assertEqual(
            exhausted.last_error_code,
            OUTBOX_RENDER_RETRY_EXHAUSTED,
        )
        self.assertEqual(valid.status, EmailOutbox.Status.SENT)
        self.assertEqual(provider.call_count, 1)

    @patch(
        "notifications.management.commands.process_email_outbox."
        "reset_email_outbox_render_failure_count"
    )
    @patch("notifications.management.commands.process_email_outbox.render_outbox_email")
    @patch("notifications.outbox_service._send_with_provider")
    def test_zero_counter_success_skips_reset_write(
        self,
        provider,
        render,
        reset_counter,
    ):
        provider.return_value = "no-reset-write"
        render.return_value = self.payload()
        outbox = self.make_outbox()

        call_command("process_email_outbox", once=True, batch_size=1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.SENT)
        reset_counter.assert_not_called()
