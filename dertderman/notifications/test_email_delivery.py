from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase, override_settings

from accounts.models import User

from notifications.email_providers.resend import ResendDeliveryError
from notifications.email_service import (
    EmailDeliveryError,
    EmailDeliveryOutcomeUnknownError,
    build_provider_idempotency_key,
    send_email,
)
from notifications.models import EmailDelivery, Notification
from notifications.provider_identifiers import (
    PROVIDER_MESSAGE_ID_MAX_LENGTH,
    ProviderMessageIdValidationError,
    ProviderMessageOwnershipError,
)


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
        EMAIL_PROVIDER=" RESEND ",
        RESEND_API_KEY="re_test_only",
        DEFAULT_FROM_EMAIL="DertDerman <info@dertderman.com>",
        EMAIL_REPLY_TO="destek@dertderman.com",
    )
    @patch("notifications.email_providers.resend.ResendProvider.send")
    def test_resend_provider_is_persisted_canonically(self, provider_send):
        provider_send.return_value = "canonical-provider-message"

        result = send_email(
            recipient_email="user@example.com",
            subject="Test",
            html_body="<p>Test</p>",
            text_body="Test",
            event_key="stage6b1:canonical-provider",
        )

        delivery = EmailDelivery.objects.get(
            idempotency_key=result.idempotency_key
        )
        self.assertEqual(delivery.provider, "resend")

    @override_settings(
        EMAIL_SENDING_ENABLED=True,
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="re_test_only",
        DEFAULT_FROM_EMAIL="DertDerman <info@dertderman.com>",
        EMAIL_REPLY_TO="destek@dertderman.com",
    )
    @patch("notifications.email_providers.resend.ResendProvider.send")
    def test_legacy_path_stores_capacity_length_id_exactly(self, provider_send):
        provider_message_id = "x" * PROVIDER_MESSAGE_ID_MAX_LENGTH
        provider_send.return_value = provider_message_id

        result = send_email(
            recipient_email="user@example.com",
            subject="Test",
            html_body="<p>Test</p>",
            text_body="Test",
            event_key="stage6b1:exact-provider-id",
        )

        delivery = EmailDelivery.objects.get(
            idempotency_key=result.idempotency_key
        )
        self.assertEqual(result.provider_message_id, provider_message_id)
        self.assertEqual(delivery.provider_message_id, provider_message_id)

    @override_settings(
        EMAIL_SENDING_ENABLED=True,
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="re_test_only",
        DEFAULT_FROM_EMAIL="DertDerman <info@dertderman.com>",
        EMAIL_REPLY_TO="destek@dertderman.com",
    )
    @patch("notifications.email_providers.resend.ResendProvider.send")
    def test_legacy_path_rejects_overlong_id_without_truncating(
        self,
        provider_send,
    ):
        provider_send.return_value = "x" * (
            PROVIDER_MESSAGE_ID_MAX_LENGTH + 1
        )
        event_key = "stage6b1:overlong-provider-id"

        with self.assertRaises(ProviderMessageIdValidationError):
            send_email(
                recipient_email="user@example.com",
                subject="Test",
                html_body="<p>Test</p>",
                text_body="Test",
                event_key=event_key,
            )

        delivery = EmailDelivery.objects.get(
            idempotency_key=build_provider_idempotency_key(
                event_key=event_key,
                recipient_email="user@example.com",
            )
        )
        self.assertEqual(delivery.status, EmailDelivery.Status.PENDING)
        self.assertEqual(delivery.provider_message_id, "")

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
    def test_definite_failed_delivery_can_be_retried_with_same_idempotency_key(
        self,
        provider_send,
    ):
        provider_send.side_effect = [
            ResendDeliveryError(
                "raw provider payload",
                code="provider_rate_limited",
                retryable=True,
                outcome_unknown=False,
            ),
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


class EmailDeliveryProviderMessageIdConstraintTests(TestCase):
    def create_delivery(self, *, provider="resend", provider_message_id=""):
        return EmailDelivery.objects.create(
            provider=provider,
            idempotency_key=f"stage6b1:{provider}:{EmailDelivery.objects.count()}",
            recipient_hash="a" * 64,
            provider_message_id=provider_message_id,
        )

    def test_same_provider_and_nonempty_message_id_is_unique(self):
        self.create_delivery(provider_message_id="shared-provider-id")

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_delivery(provider_message_id="shared-provider-id")

    def test_update_cannot_claim_another_delivery_provider_message_id(self):
        self.create_delivery(provider_message_id="owned-provider-id")
        contender = self.create_delivery(provider_message_id="")

        with self.assertRaises(IntegrityError), transaction.atomic():
            contender.provider_message_id = "owned-provider-id"
            contender.save(update_fields=["provider_message_id"])

    def test_different_providers_may_share_message_id(self):
        resend_delivery = self.create_delivery(
            provider="resend",
            provider_message_id="provider-scoped-id",
        )
        other_delivery = self.create_delivery(
            provider="other-provider",
            provider_message_id="provider-scoped-id",
        )

        self.assertNotEqual(resend_delivery.pk, other_delivery.pk)

    def test_multiple_blank_message_ids_remain_valid(self):
        pending = self.create_delivery(provider_message_id="")
        failed = self.create_delivery(provider_message_id="")
        failed.status = EmailDelivery.Status.FAILED
        failed.save(update_fields=["status"])

        self.assertEqual(pending.provider_message_id, "")
        self.assertEqual(failed.provider_message_id, "")


@override_settings(
    EMAIL_SENDING_ENABLED=True,
    EMAIL_PROVIDER="resend",
    RESEND_API_KEY="re_test_only",
    DEFAULT_FROM_EMAIL="DertDerman <info@dertderman.com>",
    EMAIL_REPLY_TO="destek@dertderman.com",
)
class LegacyAmbiguousProviderOutcomeTests(TransactionTestCase):
    def test_real_resend_invalid_response_is_quarantined_without_resend(self):
        cases = (
            (
                "overlong",
                "private-provider-id-"
                + "x" * PROVIDER_MESSAGE_ID_MAX_LENGTH,
            ),
            ("missing", ""),
        )

        for case_name, invalid_provider_message_id in cases:
            with self.subTest(case_name=case_name):
                sdk_send = Mock(
                    return_value={"id": invalid_provider_message_id}
                )
                fake_resend = SimpleNamespace(
                    api_key=None,
                    default_http_client=None,
                    Emails=SimpleNamespace(send=sdk_send),
                    RequestsClient=Mock(return_value=object()),
                )
                send_kwargs = {
                    "recipient_email": "user@example.com",
                    "subject": "Test",
                    "html_body": "<p>Test</p>",
                    "text_body": "Test",
                    "event_key": f"stage6b1:ambiguous-{case_name}",
                }

                with patch(
                    "notifications.email_providers.resend._load_resend",
                    return_value=fake_resend,
                ), self.assertNoLogs("notifications", level="DEBUG"):
                    with self.assertRaises(
                        EmailDeliveryOutcomeUnknownError
                    ) as context:
                        send_email(**send_kwargs)

                key = build_provider_idempotency_key(
                    event_key=send_kwargs["event_key"],
                    recipient_email=send_kwargs["recipient_email"],
                )
                delivery = EmailDelivery.objects.get(idempotency_key=key)
                self.assertEqual(delivery.status, EmailDelivery.Status.PENDING)
                self.assertEqual(delivery.attempt_count, 1)
                self.assertEqual(delivery.provider_message_id, "")
                self.assertIsNone(delivery.sent_at)
                self.assertEqual(
                    delivery.last_error_type,
                    EmailDeliveryOutcomeUnknownError.code,
                )
                self.assertEqual(
                    str(context.exception),
                    "Email provider outcome is unknown.",
                )
                if invalid_provider_message_id:
                    self.assertNotIn(
                        invalid_provider_message_id,
                        str(context.exception),
                    )
                    persisted_values = " ".join(
                        str(getattr(delivery, field.name))
                        for field in delivery._meta.fields
                    )
                    self.assertNotIn(
                        invalid_provider_message_id,
                        persisted_values,
                    )

                with self.assertRaises(EmailDeliveryError):
                    send_email(**send_kwargs)

                sdk_send.assert_called_once()


@override_settings(
    EMAIL_SENDING_ENABLED=True,
    EMAIL_PROVIDER="resend",
    RESEND_API_KEY="re_test_only",
    DEFAULT_FROM_EMAIL="DertDerman <info@dertderman.com>",
    EMAIL_REPLY_TO="destek@dertderman.com",
)
class LegacyProviderMessageCollisionTests(TransactionTestCase):
    @patch("notifications.email_providers.resend.ResendProvider.send")
    def test_outer_transaction_remains_usable_after_collision(
        self,
        provider_send,
    ):
        provider_message_id = "private-outer-transaction-provider-id"
        owner = EmailDelivery.objects.create(
            provider="resend",
            idempotency_key="stage6b1:outer-transaction-owner",
            recipient_hash="a" * 64,
            status=EmailDelivery.Status.SENT,
            provider_message_id=provider_message_id,
            attempt_count=1,
        )
        owner_state = (
            owner.status,
            owner.provider_message_id,
            owner.attempt_count,
            owner.last_error_type,
            owner.sent_at,
        )
        provider_send.return_value = provider_message_id
        event_key = "stage6b1:outer-transaction-collision"
        send_kwargs = {
            "recipient_email": "user@example.com",
            "subject": "Test",
            "html_body": "<p>Test</p>",
            "text_body": "Test",
            "event_key": event_key,
        }
        key = build_provider_idempotency_key(
            event_key=event_key,
            recipient_email=send_kwargs["recipient_email"],
        )

        with self.assertLogs(
            "notifications.email_service",
            level="ERROR",
        ) as captured:
            with transaction.atomic():
                try:
                    send_email(**send_kwargs)
                except ProviderMessageOwnershipError as error:
                    ownership_error = error
                else:
                    self.fail("ProviderMessageOwnershipError was not raised.")

                self.assertEqual(EmailDelivery.objects.count(), 2)
                contender = EmailDelivery.objects.get(idempotency_key=key)
                self.assertEqual(contender.status, EmailDelivery.Status.PENDING)
                self.assertEqual(contender.provider_message_id, "")
                self.assertIsNone(contender.sent_at)

        owner.refresh_from_db()
        contender.refresh_from_db()
        self.assertEqual(
            (
                owner.status,
                owner.provider_message_id,
                owner.attempt_count,
                owner.last_error_type,
                owner.sent_at,
            ),
            owner_state,
        )
        self.assertEqual(contender.status, EmailDelivery.Status.PENDING)
        self.assertEqual(contender.provider_message_id, "")
        self.assertIsNone(contender.sent_at)
        self.assertEqual(
            ownership_error.code,
            "provider_message_ownership_conflict",
        )
        self.assertNotIn(provider_message_id, " ".join(captured.output))
        provider_send.assert_called_once()

        with self.assertRaises(EmailDeliveryError):
            send_email(**send_kwargs)

        provider_send.assert_called_once()

    @patch("notifications.email_providers.resend.ResendProvider.send")
    def test_autocommit_collision_quarantines_contender_without_resending(
        self,
        provider_send,
    ):
        provider_message_id = "private-shared-provider-id"
        owner = EmailDelivery.objects.create(
            provider="resend",
            idempotency_key="stage6b1:legacy-provider-message-owner",
            recipient_hash="a" * 64,
            status=EmailDelivery.Status.SENT,
            provider_message_id=provider_message_id,
            attempt_count=1,
        )
        owner_state = (
            owner.status,
            owner.provider_message_id,
            owner.attempt_count,
            owner.last_error_type,
            owner.sent_at,
        )
        provider_send.return_value = provider_message_id
        event_key = "stage6b1:legacy-provider-message-collision"
        send_kwargs = {
            "recipient_email": "user@example.com",
            "subject": "Test",
            "html_body": "<p>Test</p>",
            "text_body": "Test",
            "event_key": event_key,
        }

        with self.assertLogs(
            "notifications.email_service",
            level="ERROR",
        ) as captured:
            with self.assertRaises(ProviderMessageOwnershipError) as context:
                send_email(**send_kwargs)

        key = build_provider_idempotency_key(
            event_key=event_key,
            recipient_email="user@example.com",
        )
        contender = EmailDelivery.objects.get(idempotency_key=key)
        owner.refresh_from_db()
        self.assertEqual(
            (
                owner.status,
                owner.provider_message_id,
                owner.attempt_count,
                owner.last_error_type,
                owner.sent_at,
            ),
            owner_state,
        )
        # PENDING deliberately quarantines the ambiguous legacy attempt. The
        # existing PENDING guard blocks another provider call until operators
        # resolve the ownership conflict.
        self.assertEqual(contender.status, EmailDelivery.Status.PENDING)
        self.assertEqual(contender.provider_message_id, "")
        self.assertIsNone(contender.sent_at)
        self.assertEqual(
            context.exception.code,
            "provider_message_ownership_conflict",
        )
        self.assertNotIn(provider_message_id, " ".join(captured.output))
        provider_send.assert_called_once()

        with self.assertRaises(EmailDeliveryError):
            send_email(**send_kwargs)

        provider_send.assert_called_once()
