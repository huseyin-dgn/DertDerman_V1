from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from notifications.email_providers.resend import (
    ResendConfigurationError,
    ResendDeliveryError,
    ResendProvider,
)
from notifications.email_service import (
    EmailConfigurationError,
    EmailDeliveryError,
    build_provider_idempotency_key,
    send_email,
)


class EmailServiceTests(SimpleTestCase):
    def test_idempotency_key_is_stable_per_event_and_recipient(self):
        first = build_provider_idempotency_key(
            event_key="complaint:10:published",
            recipient_email="User@Example.com",
        )
        second = build_provider_idempotency_key(
            event_key="complaint:10:published",
            recipient_email="user@example.com",
        )
        other_recipient = build_provider_idempotency_key(
            event_key="complaint:10:published",
            recipient_email="other@example.com",
        )

        self.assertEqual(first, second)
        self.assertNotEqual(first, other_recipient)
        self.assertLessEqual(len(first), 256)
        self.assertNotIn("user@example.com", first)

    @override_settings(
        EMAIL_SENDING_ENABLED=False,
        EMAIL_PROVIDER="resend",
    )
    def test_disabled_delivery_is_a_safe_noop(self):
        result = send_email(
            recipient_email="user@example.com",
            subject="Test",
            html_body="<p>Test</p>",
            text_body="Test",
            event_key="test:disabled",
        )

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.provider, "resend")
        self.assertIsNone(result.provider_message_id)

    @override_settings(
        EMAIL_SENDING_ENABLED=True,
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="re_test_only",
        DEFAULT_FROM_EMAIL="DertDerman <info@dertderman.com>",
        EMAIL_REPLY_TO="destek@dertderman.com",
    )
    @patch("notifications.email_providers.resend.ResendProvider.send")
    def test_service_passes_complete_message_to_provider(self, provider_send):
        provider_send.return_value = "provider-message-123"

        result = send_email(
            recipient_email="user@example.com",
            subject="Hesap bildirimi",
            html_body="<p>Merhaba</p>",
            text_body="Merhaba",
            event_key="account:1:test",
        )

        self.assertEqual(result.status, "sent")
        self.assertEqual(result.provider_message_id, "provider-message-123")
        provider_send.assert_called_once()
        kwargs = provider_send.call_args.kwargs
        self.assertEqual(kwargs["from_email"], "DertDerman <info@dertderman.com>")
        self.assertEqual(kwargs["reply_to"], "destek@dertderman.com")
        self.assertEqual(kwargs["html_body"], "<p>Merhaba</p>")
        self.assertEqual(kwargs["text_body"], "Merhaba")
        self.assertTrue(kwargs["idempotency_key"].startswith("dertderman/"))

    @override_settings(
        EMAIL_SENDING_ENABLED=True,
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="",
        DEFAULT_FROM_EMAIL="DertDerman <info@dertderman.com>",
        EMAIL_REPLY_TO="destek@dertderman.com",
    )
    def test_missing_api_key_fails_closed(self):
        with self.assertRaises(EmailConfigurationError):
            send_email(
                recipient_email="user@example.com",
                subject="Test",
                html_body="<p>Test</p>",
                text_body="Test",
                event_key="test:missing-key",
            )

    @override_settings(
        EMAIL_SENDING_ENABLED=True,
        EMAIL_PROVIDER="resend",
        RESEND_API_KEY="re_test_only",
        DEFAULT_FROM_EMAIL="DertDerman <info@dertderman.com>",
        EMAIL_REPLY_TO="destek@dertderman.com",
    )
    @patch(
        "notifications.email_providers.resend.ResendProvider.send",
        side_effect=ResendDeliveryError("raw provider detail"),
    )
    def test_provider_failure_is_wrapped_without_raw_detail(self, _provider_send):
        with self.assertRaises(EmailDeliveryError) as context:
            send_email(
                recipient_email="user@example.com",
                subject="Test",
                html_body="<p>Test</p>",
                text_body="Test",
                event_key="test:provider-failure",
            )

        self.assertNotIn("raw provider detail", str(context.exception))

    def test_invalid_recipient_is_rejected_before_transport(self):
        with self.assertRaises(EmailConfigurationError):
            send_email(
                recipient_email="not-an-email",
                subject="Test",
                html_body="<p>Test</p>",
                text_body="Test",
                event_key="test:invalid-email",
            )


class ResendProviderTests(SimpleTestCase):
    def test_provider_requires_api_key(self):
        with self.assertRaises(ResendConfigurationError):
            ResendProvider(api_key="")

    @patch("notifications.email_providers.resend._load_resend")
    def test_provider_uses_reply_to_text_html_and_idempotency(self, load_resend):
        emails = SimpleNamespace(send=Mock(return_value={"id": "resend-id-1"}))
        fake_resend = SimpleNamespace(api_key=None, Emails=emails)
        load_resend.return_value = fake_resend

        provider = ResendProvider(api_key="re_test_only")
        provider_id = provider.send(
            recipient_email="user@example.com",
            subject="Test",
            html_body="<p>HTML</p>",
            text_body="TEXT",
            from_email="DertDerman <info@dertderman.com>",
            reply_to="destek@dertderman.com",
            idempotency_key="dertderman/test-key",
        )

        self.assertEqual(provider_id, "resend-id-1")
        self.assertEqual(fake_resend.api_key, "re_test_only")
        params = emails.send.call_args.args[0]
        options = emails.send.call_args.kwargs["options"]
        self.assertEqual(params["to"], ["user@example.com"])
        self.assertEqual(params["reply_to"], "destek@dertderman.com")
        self.assertEqual(params["html"], "<p>HTML</p>")
        self.assertEqual(params["text"], "TEXT")
        self.assertEqual(options["idempotency_key"], "dertderman/test-key")

    @patch("notifications.email_providers.resend._load_resend")
    def test_provider_does_not_expose_raw_provider_failure(self, load_resend):
        emails = SimpleNamespace(send=Mock(side_effect=RuntimeError("secret-ish payload")))
        load_resend.return_value = SimpleNamespace(api_key=None, Emails=emails)

        provider = ResendProvider(api_key="re_test_only")

        with self.assertRaises(ResendDeliveryError) as context:
            provider.send(
                recipient_email="user@example.com",
                subject="Test",
                html_body="<p>HTML</p>",
                text_body="TEXT",
                from_email="DertDerman <info@dertderman.com>",
                reply_to="destek@dertderman.com",
                idempotency_key="dertderman/test-key",
            )

        self.assertNotIn("secret-ish payload", str(context.exception))
