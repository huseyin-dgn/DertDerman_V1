from unittest.mock import patch

from django.test import TestCase, override_settings

from accounts.models import User

from notifications.email_providers.resend import ResendDeliveryError
from notifications.email_service import (
    EmailDeliveryError,
    build_provider_idempotency_key,
    send_email,
)
from notifications.models import EmailDelivery, Notification


class EmailDeliveryPersistenceTests(TestCase):
    @override_settings(
        EMAIL_SENDING_ENABLED=False,
        EMAIL_PROVIDER="resend",
    )
    def test_disabled_email_is_persisted_as_skipped_without_raw_address(self):
        result = send_email(
            recipient_email="User@Example.com",
            subject="Test",
            html_body="<p>Test</p>",
            text_body="Test",
            event_key="stage6:disabled:1",
        )

        delivery = EmailDelivery.objects.get(
            idempotency_key=result.idempotency_key
        )

        self.assertEqual(delivery.status, EmailDelivery.Status.SKIPPED)
        self.assertEqual(delivery.attempt_count, 0)
        self.assertEqual(len(delivery.recipient_hash), 64)
        self.assertNotEqual(delivery.recipient_hash, "user@example.com")
        self.assertNotIn(
            "recipient_email",
            {field.name for field in EmailDelivery._meta.fields},
        )

    @patch("notifications.email_providers.resend.ResendProvider.send")
    def test_skipped_delivery_is_sent_when_sending_is_later_enabled(
        self,
        provider_send,
    ):
        kwargs = {
            "recipient_email": "user@example.com",
            "subject": "Test",
            "html_body": "<p>Test</p>",
            "text_body": "Test",
            "event_key": "stage6:skipped-then-enabled:1",
        }

        with self.settings(
            EMAIL_SENDING_ENABLED=False,
            EMAIL_PROVIDER="resend",
        ):
            first = send_email(**kwargs)

        delivery = EmailDelivery.objects.get(
            idempotency_key=first.idempotency_key
        )
        self.assertEqual(first.status, "skipped")
        self.assertEqual(delivery.status, EmailDelivery.Status.SKIPPED)
        self.assertEqual(delivery.attempt_count, 0)
        provider_send.assert_not_called()

        provider_send.return_value = "resend-message-after-skip"

        with self.settings(
            EMAIL_SENDING_ENABLED=True,
            EMAIL_PROVIDER="resend",
            RESEND_API_KEY="re_test_only",
            DEFAULT_FROM_EMAIL="DertDerman <info@dertderman.com>",
            EMAIL_REPLY_TO="destek@dertderman.com",
        ):
            second = send_email(**kwargs)

        delivery.refresh_from_db()
        self.assertEqual(first.idempotency_key, second.idempotency_key)
        self.assertEqual(second.status, "sent")
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(
            delivery.provider_message_id,
            "resend-message-after-skip",
        )
        provider_send.assert_called_once()

    @override_settings(
        EMAIL_SENDING_ENABLED=True,
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="re_test_only",
        DEFAULT_FROM_EMAIL="DertDerman <info@dertderman.com>",
        EMAIL_REPLY_TO="destek@dertderman.com",
    )
    @patch("notifications.email_providers.resend.ResendProvider.send")
    def test_success_is_persisted_with_provider_message_id(self, provider_send):
        provider_send.return_value = "resend-message-1"

        result = send_email(
            recipient_email="user@example.com",
            subject="Test",
            html_body="<p>Test</p>",
            text_body="Test",
            event_key="stage6:sent:1",
        )

        delivery = EmailDelivery.objects.get(
            idempotency_key=result.idempotency_key
        )

        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)
        self.assertEqual(delivery.provider, "resend")
        self.assertEqual(delivery.provider_message_id, "resend-message-1")
        self.assertEqual(delivery.attempt_count, 1)
        self.assertIsNotNone(delivery.sent_at)
        self.assertEqual(delivery.last_error_type, "")

    @override_settings(
        EMAIL_SENDING_ENABLED=True,
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="re_test_only",
        DEFAULT_FROM_EMAIL="DertDerman <info@dertderman.com>",
        EMAIL_REPLY_TO="destek@dertderman.com",
    )
    @patch("notifications.email_providers.resend.ResendProvider.send")
    def test_sent_delivery_is_idempotent_across_repeated_calls(self, provider_send):
        provider_send.return_value = "resend-message-2"
        kwargs = {
            "recipient_email": "user@example.com",
            "subject": "Test",
            "html_body": "<p>Test</p>",
            "text_body": "Test",
            "event_key": "stage6:idempotent:1",
        }

        first = send_email(**kwargs)
        second = send_email(**kwargs)

        self.assertEqual(first.idempotency_key, second.idempotency_key)
        self.assertEqual(second.status, "sent")
        self.assertEqual(second.provider_message_id, "resend-message-2")
        self.assertEqual(EmailDelivery.objects.count(), 1)
        provider_send.assert_called_once()

    @override_settings(
        EMAIL_SENDING_ENABLED=True,
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="re_test_only",
        DEFAULT_FROM_EMAIL="DertDerman <info@dertderman.com>",
        EMAIL_REPLY_TO="destek@dertderman.com",
    )
    @patch("notifications.email_providers.resend.ResendProvider.send")
    def test_failed_delivery_can_be_caller_retried_with_same_idempotency_key(
        self,
        provider_send,
    ):
        provider_send.side_effect = [
            ResendDeliveryError("raw provider payload"),
            "resend-message-retry",
        ]

        kwargs = {
            "recipient_email": "user@example.com",
            "subject": "Test",
            "html_body": "<p>Test</p>",
            "text_body": "Test",
            "event_key": "stage6:retry:1",
        }

        with self.assertRaises(EmailDeliveryError):
            send_email(**kwargs)

        key = build_provider_idempotency_key(
            event_key=kwargs["event_key"],
            recipient_email=kwargs["recipient_email"],
        )
        delivery = EmailDelivery.objects.get(idempotency_key=key)
        self.assertEqual(delivery.status, EmailDelivery.Status.FAILED)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(delivery.last_error_type, "EmailDeliveryError")
        self.assertNotIn("raw provider payload", delivery.last_error_type)

        result = send_email(**kwargs)

        delivery.refresh_from_db()
        self.assertEqual(result.status, "sent")
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)
        self.assertEqual(delivery.attempt_count, 2)
        self.assertEqual(
            delivery.provider_message_id,
            "resend-message-retry",
        )
        self.assertEqual(provider_send.call_count, 2)

    @override_settings(
        EMAIL_SENDING_ENABLED=True,
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="re_test_only",
        DEFAULT_FROM_EMAIL="DertDerman <info@dertderman.com>",
        EMAIL_REPLY_TO="destek@dertderman.com",
    )
    @patch("notifications.email_providers.resend.ResendProvider.send")
    def test_existing_pending_delivery_blocks_second_transport_call(
        self,
        provider_send,
    ):
        event_key = "stage6:pending:1"
        recipient = "user@example.com"
        key = build_provider_idempotency_key(
            event_key=event_key,
            recipient_email=recipient,
        )
        EmailDelivery.objects.create(
            provider="resend",
            idempotency_key=key,
            recipient_hash="0" * 64,
            status=EmailDelivery.Status.PENDING,
            attempt_count=1,
        )

        with self.assertRaises(EmailDeliveryError):
            send_email(
                recipient_email=recipient,
                subject="Test",
                html_body="<p>Test</p>",
                text_body="Test",
                event_key=event_key,
            )

        provider_send.assert_not_called()

    @override_settings(
        EMAIL_SENDING_ENABLED=False,
        EMAIL_PROVIDER="resend",
    )
    def test_delivery_can_reference_notification_without_storing_message_body(self):
        user = User.objects.create_user(
            username="stage6-user",
            email="stage6-user@example.com",
            password="StrongRiver#9284",
            user_type=User.UserType.USER,
            is_active=True,
            is_verified=True,
        )
        notification = Notification.objects.create(
            recipient_user=user,
            recipient_role=Notification.Scope.USER,
            notification_type=Notification.Type.PUBLISHED,
            event_key="stage6:notification:1",
            title="Şikayetiniz yayınlandı.",
            message="Bu metin EmailDelivery tablosuna kopyalanmamalı.",
        )

        result = send_email(
            recipient_email=user.email,
            subject="Test",
            html_body="<p>Secret-ish body</p>",
            text_body="Secret-ish body",
            event_key="stage6:notification-email:1",
            notification=notification,
        )

        delivery = EmailDelivery.objects.get(
            idempotency_key=result.idempotency_key
        )
        self.assertEqual(delivery.notification_id, notification.pk)

        field_names = {field.name for field in EmailDelivery._meta.fields}
        self.assertNotIn("subject", field_names)
        self.assertNotIn("html_body", field_names)
        self.assertNotIn("text_body", field_names)
