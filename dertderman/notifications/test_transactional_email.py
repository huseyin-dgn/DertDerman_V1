from datetime import timedelta
from unittest.mock import PropertyMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import User
from companies.models import Company
from complaints.models import Complaint

from .email_policy import notification_email_policy
from .email_providers.resend import ResendDeliveryError
from .models import EmailDelivery, EmailOutbox, Notification
from .outbox_service import (
    OUTBOX_INVALID_RECIPE,
    OUTBOX_UNSUPPORTED_TEMPLATE_VERSION,
    claim_email_outbox,
    render_outbox_email,
    send_outbox_email,
)
from .services import send
from .transactional_email import (
    NOTIFICATION_POLICY_CHANGED,
    build_notification_target_url,
    enqueue_notification_email,
)


EMAIL_SETTINGS = {
    "TRANSACTIONAL_EMAILS_ENABLED": True,
    "EMAIL_SENDING_ENABLED": True,
    "EMAIL_PROVIDER": "resend",
    "RESEND_API_KEY": "re_test_only",
    "SITE_BASE_URL": "https://dertderman.com",
    "DEFAULT_FROM_EMAIL": "DertDerman <info@dertderman.com>",
    "EMAIL_REPLY_TO": "destek@dertderman.com",
}


class NotificationFixtureMixin:
    def make_fixtures(self):
        self.user = User.objects.create_user(
            username="mail-user",
            email="mail-user@example.com",
            password="StrongRiver#9284",
            user_type=User.UserType.USER,
            is_active=True,
            is_verified=True,
        )
        self.unverified = User.objects.create_user(
            username="unverified-mail-user",
            email="unverified-mail-user@example.com",
            password="StrongRiver#9284",
            user_type=User.UserType.USER,
            is_active=True,
            is_verified=False,
        )
        self.admin = User.objects.create_user(
            username="mail-admin",
            email="mail-admin@example.com",
            password="StrongRiver#9284",
            user_type=User.UserType.ADMIN,
            is_active=True,
            is_verified=True,
        )
        self.company_user = User.objects.create_user(
            username="mail-company-user",
            email="mail-company-user@example.com",
            password="StrongRiver#9284",
            user_type=User.UserType.COMPANY,
            is_active=True,
            is_verified=True,
        )
        self.inactive = User.objects.create_user(
            username="inactive-mail-user",
            email="inactive-mail-user@example.com",
            password="StrongRiver#9284",
            user_type=User.UserType.USER,
            is_active=False,
            is_verified=True,
        )
        self.company = Company.objects.create(name="Mail Company", is_verified=True)
        self.complaint = Complaint.objects.create(
            user=self.user,
            company=self.company,
            title="Mail bildirim testi",
            description="Transactional email testi için yeterli açıklama metni.",
        )

    def send_event(
        self,
        *,
        recipient=None,
        scope=Notification.Scope.USER,
        kind=Notification.Type.PUBLISHED,
        event_key="mail-test:1",
        title="Şikayetiniz yayınlandı.",
        message="Şikayetiniz artık yayında.",
        complaint=True,
    ):
        return send(
            recipient=recipient or self.user,
            scope=scope,
            kind=kind,
            event_key=event_key,
            title=title,
            message=message,
            complaint=self.complaint if complaint else None,
            company=self.company if complaint else None,
        )

    def create_notification(self, **overrides):
        values = {
            "recipient_user": self.user,
            "recipient_role": Notification.Scope.USER,
            "notification_type": Notification.Type.PUBLISHED,
            "event_key": "direct-policy:1",
            "title": "Şikayetiniz yayınlandı.",
            "message": "Şikayetiniz artık yayında.",
            "complaint": self.complaint,
        }
        values.update(overrides)
        return Notification.objects.create(**values)


@override_settings(**EMAIL_SETTINGS)
class TransactionalNotificationProducerTests(NotificationFixtureMixin, TestCase):
    def setUp(self):
        self.make_fixtures()

    def test_eligible_notification_and_outbox_are_created_without_inline_work(self):
        with (
            patch("notifications.email_service.send_email") as send_email,
            patch(
                "notifications.email_providers.resend.ResendProvider.send"
            ) as provider_send,
            patch("notifications.transactional_email.render_to_string") as render,
            patch("django.db.transaction.on_commit") as on_commit,
        ):
            notification = self.send_event()

        outbox = EmailOutbox.objects.get()
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(outbox.kind, EmailOutbox.Kind.NOTIFICATION)
        self.assertEqual(outbox.status, EmailOutbox.Status.PENDING)
        self.assertEqual(outbox.recipient_user, self.user)
        self.assertEqual(outbox.notification, notification)
        self.assertTrue(outbox.recipient_hash)
        self.assertEqual(outbox.request_state_hash, "")
        self.assertIsNone(outbox.token_issued_at)
        self.assertEqual(EmailDelivery.objects.count(), 0)
        outbox_values = [
            str(getattr(outbox, field.attname))
            for field in EmailOutbox._meta.concrete_fields
            if field.attname not in {"recipient_user_id", "notification_id"}
        ]
        self.assertNotIn(self.user.email, outbox_values)
        self.assertNotIn(notification.message, outbox_values)
        send_email.assert_not_called()
        provider_send.assert_not_called()
        render.assert_not_called()
        on_commit.assert_not_called()

    def test_duplicate_event_returns_same_notification_and_does_not_reenqueue(self):
        with patch(
            "notifications.transactional_email.enqueue_notification_email",
            wraps=enqueue_notification_email,
        ) as enqueue:
            first = self.send_event(event_key="duplicate:1")
            second = self.send_event(event_key="duplicate:1")

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(EmailOutbox.objects.count(), 1)
        enqueue.assert_called_once_with(first)

    def test_social_and_routine_events_create_notification_without_outbox(self):
        kinds = ("LIKE", "REACTION", "COMMENT", "RECEIVED", "UPDATED", "MODERATION")
        for kind in kinds:
            with self.subTest(kind=kind):
                self.send_event(kind=kind, event_key=f"not-emailed:{kind}")
        self.assertEqual(Notification.objects.count(), len(kinds))
        self.assertFalse(EmailOutbox.objects.exists())

    def test_admin_recipient_creates_notification_without_outbox(self):
        notification = self.send_event(
            recipient=self.admin,
            scope=Notification.Scope.ADMIN,
            kind=Notification.Type.CONTENT_REPORT,
            event_key="admin-report:1",
            complaint=False,
        )
        self.assertIsNotNone(notification)
        self.assertFalse(EmailOutbox.objects.exists())

    def test_policy_excludes_unverified_inactive_and_non_user_recipients(self):
        cases = (
            (self.unverified, Notification.Scope.USER),
            (self.inactive, Notification.Scope.USER),
            (self.company_user, Notification.Scope.USER),
        )
        for index, (recipient, scope) in enumerate(cases):
            notification = self.create_notification(
                recipient_user=recipient,
                recipient_role=scope,
                event_key=f"policy-user:{index}",
            )
            self.assertFalse(notification_email_policy(notification).should_send)
            self.assertIsNone(enqueue_notification_email(notification))
        self.assertFalse(EmailOutbox.objects.exists())

    @override_settings(TRANSACTIONAL_EMAILS_ENABLED=False)
    def test_disabled_policy_keeps_notification_without_outbox(self):
        notification = self.send_event(event_key="disabled:1")
        self.assertIsNotNone(notification)
        self.assertFalse(EmailOutbox.objects.exists())

    @override_settings(EMAIL_SENDING_ENABLED=False, RESEND_API_KEY="")
    def test_missing_provider_configuration_does_not_block_enqueue(self):
        notification = self.send_event(event_key="provider-config:1")
        self.assertIsNotNone(notification)
        self.assertEqual(EmailOutbox.objects.count(), 1)

    def test_outbox_creation_failure_rolls_back_notification(self):
        with patch(
            "notifications.transactional_email.EmailOutbox.objects.create",
            side_effect=RuntimeError("outbox unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                self.send_event(event_key="atomic-failure:1")
        self.assertFalse(Notification.objects.filter(event_key="atomic-failure:1").exists())
        self.assertFalse(EmailOutbox.objects.exists())

    def test_outer_transaction_rollback_removes_notification_and_outbox(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.send_event(event_key="outer-rollback:1")
                raise RuntimeError("rollback caller")
        self.assertFalse(Notification.objects.filter(event_key="outer-rollback:1").exists())
        self.assertFalse(EmailOutbox.objects.exists())

    def test_existing_target_url_and_policy_rules_are_preserved(self):
        notification = self.create_notification(event_key="private-url:1")
        self.assertTrue(notification_email_policy(notification).should_send)
        private_url = build_notification_target_url(notification)
        self.assertIn(f"/sikayetlerim/{self.complaint.pk}/", private_url)
        self.assertNotIn(f"/sikayetler/{self.complaint.pk}/", private_url)

        Complaint.objects.filter(pk=self.complaint.pk).update(
            status=Complaint.Status.PUBLISHED
        )
        self.complaint.refresh_from_db()
        public = self.create_notification(event_key="public-url:1")
        self.assertEqual(
            build_notification_target_url(public),
            f"https://dertderman.com/sikayetler/{self.complaint.pk}/",
        )
        self.assertEqual(self.client.get(f"/sikayetler/{self.complaint.pk}/").status_code, 200)


@override_settings(**EMAIL_SETTINGS)
class TransactionalNotificationWorkerTests(
    NotificationFixtureMixin, TransactionTestCase
):
    reset_sequences = True

    def setUp(self):
        self.make_fixtures()
        resend_loader = patch("notifications.outbox_service._load_resend")
        resend_loader.start().return_value = object()
        self.addCleanup(resend_loader.stop)

    def enqueue(self, *, event_key="worker:1"):
        notification = self.send_event(event_key=event_key)
        return notification, notification.email_outbox_item

    def claim(self, outbox):
        claims = claim_email_outbox(batch_size=100)
        claim = next(item for item in claims if item.outbox_id == outbox.pk)
        outbox.refresh_from_db()
        return claim

    @patch("notifications.outbox_service._send_with_provider", return_value="resend-1")
    def test_worker_renders_and_sends_actionable_notification(self, provider_send):
        notification, outbox = self.enqueue()
        call_command("process_email_outbox", "--once")
        outbox.refresh_from_db()
        payload = provider_send.call_args.args[1]
        self.assertEqual(outbox.status, EmailOutbox.Status.SENT)
        self.assertIn(notification.title.rstrip("."), payload.subject)
        self.assertIn("https://dertderman.com/", payload.html_body)
        self.assertIn("https://dertderman.com/", payload.text_body)

    @patch("notifications.outbox_service._send_with_provider")
    def test_unsupported_template_version_is_dead_without_attempt(
        self, provider_send
    ):
        _notification, outbox = self.enqueue()
        EmailOutbox.objects.filter(pk=outbox.pk).update(template_version=2)

        call_command("process_email_outbox", "--once")

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.DEAD)
        self.assertEqual(
            outbox.last_error_code,
            OUTBOX_UNSUPPORTED_TEMPLATE_VERSION,
        )
        self.assertEqual(outbox.attempt_count, 0)
        self.assertIsNone(outbox.first_attempt_at)
        self.assertIsNone(outbox.provider_retry_deadline_at)
        self.assertEqual(outbox.payload_hash, "")
        self.assertFalse(EmailDelivery.objects.filter(outbox=outbox).exists())
        provider_send.assert_not_called()

    @patch("notifications.outbox_service._send_with_provider")
    def test_invalid_notification_target_is_dead_without_attempt(
        self, provider_send
    ):
        _notification, outbox = self.enqueue()

        with patch.object(
            Notification,
            "target_url",
            new_callable=PropertyMock,
            return_value="https://attacker.example/path",
        ):
            call_command("process_email_outbox", "--once")

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.DEAD)
        self.assertEqual(outbox.last_error_code, OUTBOX_INVALID_RECIPE)
        self.assertEqual(outbox.attempt_count, 0)
        self.assertFalse(EmailDelivery.objects.filter(outbox=outbox).exists())
        provider_send.assert_not_called()

    @patch("notifications.outbox_service._send_with_provider")
    def test_business_cancellation_precedes_stored_provider_mismatch(
        self, provider_send
    ):
        notification, outbox = self.enqueue()
        original_render = render_outbox_email

        def render_then_invalidate_business_state(item):
            payload = original_render(item)
            User.objects.filter(pk=notification.recipient_user_id).update(
                is_active=False
            )
            EmailOutbox.objects.filter(pk=item.pk).update(
                provider="corrupt-provider"
            )
            return payload

        with patch(
            "notifications.management.commands.process_email_outbox."
            "render_outbox_email",
            side_effect=render_then_invalidate_business_state,
        ):
            call_command("process_email_outbox", "--once")

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.CANCELLED)
        self.assertNotEqual(outbox.status, EmailOutbox.Status.DEAD)
        self.assertEqual(outbox.last_error_code, NOTIFICATION_POLICY_CHANGED)
        self.assertEqual(outbox.attempt_count, 0)
        self.assertFalse(EmailDelivery.objects.filter(outbox=outbox).exists())
        provider_send.assert_not_called()

    @patch("notifications.outbox_service._send_with_provider")
    def test_worker_policy_change_cancels_without_attempt(self, provider_send):
        _notification, outbox = self.enqueue()
        with self.settings(TRANSACTIONAL_EMAILS_ENABLED=False):
            call_command("process_email_outbox", "--once")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.CANCELLED)
        self.assertEqual(outbox.last_error_code, "NOTIFICATION_POLICY_CHANGED")
        self.assertEqual(outbox.attempt_count, 0)
        self.assertFalse(EmailDelivery.objects.exists())
        provider_send.assert_not_called()

    @patch("notifications.outbox_service._send_with_provider")
    def test_worker_rechecks_all_recipient_and_type_policy_inputs(self, provider_send):
        outboxes = []
        mutations = (
            lambda user, notification: setattr(user, "is_active", False),
            lambda user, notification: setattr(user, "is_verified", False),
            lambda user, notification: setattr(
                user, "user_type", User.UserType.COMPANY
            ),
            lambda user, notification: setattr(user, "is_permanently_closed", True),
            lambda user, notification: setattr(user, "email", ""),
            lambda user, notification: setattr(
                notification, "notification_type", "LIKE"
            ),
        )
        for index, mutate in enumerate(mutations):
            user = User.objects.create_user(
                username=f"policy-worker-{index}",
                email=f"policy-worker-{index}@example.com",
                password="StrongRiver#9284",
                user_type=User.UserType.USER,
                is_active=True,
                is_verified=True,
            )
            notification = self.send_event(
                recipient=user,
                event_key=f"policy-worker:{index}",
            )
            outboxes.append(notification.email_outbox_item)
            mutate(user, notification)
            user.save()
            notification.save()

        call_command("process_email_outbox", "--once")

        for outbox in outboxes:
            outbox.refresh_from_db()
            self.assertEqual(outbox.status, EmailOutbox.Status.CANCELLED)
            self.assertEqual(outbox.last_error_code, "NOTIFICATION_POLICY_CHANGED")
            self.assertEqual(outbox.attempt_count, 0)
        self.assertFalse(EmailDelivery.objects.exists())
        provider_send.assert_not_called()

    @patch("notifications.outbox_service._send_with_provider")
    def test_recipient_change_is_cancelled_before_provider(self, provider_send):
        _notification, outbox = self.enqueue()
        self.user.email = "changed-mail-user@example.com"
        self.user.save(update_fields=["email"])
        call_command("process_email_outbox", "--once")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.CANCELLED)
        self.assertEqual(outbox.last_error_code, "RECIPIENT_CHANGED")
        self.assertEqual(outbox.attempt_count, 0)
        self.assertFalse(EmailDelivery.objects.exists())
        provider_send.assert_not_called()

    @patch("notifications.outbox_service._send_with_provider")
    def test_global_render_configuration_failure_happens_before_claim(
        self,
        provider_send,
    ):
        _notification, outbox = self.enqueue()
        with self.settings(SITE_BASE_URL=""):
            with self.assertRaises(CommandError):
                call_command("process_email_outbox", "--once")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.PENDING)
        self.assertEqual(outbox.last_error_code, "")
        self.assertIsNone(outbox.claim_token)
        self.assertEqual(outbox.attempt_count, 0)
        self.assertFalse(EmailDelivery.objects.exists())
        provider_send.assert_not_called()

    @patch("notifications.outbox_service._send_with_provider")
    def test_retry_reuses_payload_delivery_and_idempotency_key(self, provider_send):
        _notification, outbox = self.enqueue()
        first_claim = self.claim(outbox)
        first_payload = render_outbox_email(outbox)
        provider_send.side_effect = ResendDeliveryError(code="provider_network_error")
        first = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=first_claim.claim_token,
            payload=first_payload,
        )
        delivery_id = EmailDelivery.objects.get(outbox=outbox).pk
        EmailOutbox.objects.filter(pk=outbox.pk).update(available_at=timezone.now())
        second_claim = self.claim(outbox)
        second_payload = render_outbox_email(outbox)
        provider_send.side_effect = None
        provider_send.return_value = "resend-retry"
        second = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=second_claim.claim_token,
            payload=second_payload,
        )
        self.assertEqual(first_payload, second_payload)
        self.assertEqual(first.idempotency_key, second.idempotency_key)
        self.assertEqual(EmailDelivery.objects.get(outbox=outbox).pk, delivery_id)
        self.assertEqual(first.status, "retry")
        self.assertEqual(second.status, "sent")

    @patch("notifications.outbox_service._send_with_provider")
    def test_changed_payload_after_attempt_is_dead_without_second_send(self, provider_send):
        notification, outbox = self.enqueue()
        first_claim = self.claim(outbox)
        provider_send.side_effect = ResendDeliveryError(code="provider_network_error")
        send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=first_claim.claim_token,
            payload=render_outbox_email(outbox),
        )
        Notification.objects.filter(pk=notification.pk).update(title="Değişmiş başlık")
        EmailOutbox.objects.filter(pk=outbox.pk).update(available_at=timezone.now())
        second_claim = self.claim(outbox)
        result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=second_claim.claim_token,
            payload=render_outbox_email(outbox),
        )
        outbox.refresh_from_db()
        self.assertEqual(result.status, "dead")
        self.assertEqual(outbox.last_error_code, "PAYLOAD_HASH_MISMATCH")
        self.assertEqual(provider_send.call_count, 1)

    @patch("notifications.outbox_service._send_with_provider")
    def test_transient_provider_failure_preserves_stage_one_retry(self, provider_send):
        _notification, outbox = self.enqueue()
        provider_send.side_effect = ResendDeliveryError(
            code="rate_limit_exceeded",
            retryable=True,
            retry_after_seconds=10,
        )
        call_command("process_email_outbox", "--once")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.RETRY)
        self.assertEqual(outbox.attempt_count, 1)
        self.assertEqual(outbox.delivery.attempt_count, 1)
        self.assertEqual(outbox.last_error_code, "rate_limit_exceeded")

    def test_deleted_notification_cascade_does_not_stop_next_item(self):
        deleted_notification, deleted_outbox = self.enqueue(event_key="deleted:1")
        survivor_notification, survivor = self.enqueue(event_key="survivor:1")
        original_render = render_outbox_email

        def delete_or_render(item):
            if item.pk == deleted_outbox.pk:
                deleted_notification.delete()
            return original_render(item)

        with (
            patch(
                "notifications.management.commands.process_email_outbox.render_outbox_email",
                side_effect=delete_or_render,
            ),
            patch(
                "notifications.outbox_service._send_with_provider",
                return_value="resend-survivor",
            ) as provider_send,
        ):
            call_command("process_email_outbox", "--once")
        self.assertFalse(EmailOutbox.objects.filter(pk=deleted_outbox.pk).exists())
        survivor.refresh_from_db()
        self.assertEqual(survivor.status, EmailOutbox.Status.SENT)
        self.assertEqual(provider_send.call_count, 1)
