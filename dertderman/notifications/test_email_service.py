import json
from importlib import metadata
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase, override_settings

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


class EmailServiceTests(TestCase):
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
    send_kwargs = {
        "recipient_email": "user@example.com",
        "subject": "Test",
        "html_body": "<p>HTML</p>",
        "text_body": "TEXT",
        "from_email": "DertDerman <info@dertderman.com>",
        "reply_to": "destek@dertderman.com",
        "idempotency_key": "dertderman/test-key",
    }

    def sdk_response(self, status, error_type, *, headers=None, message="rejected"):
        response_headers = {"content-type": "application/json"}
        response_headers.update(headers or {})
        return SimpleNamespace(
            content=json.dumps(
                {
                    "statusCode": status,
                    "name": error_type,
                    "message": message,
                }
            ).encode("utf-8"),
            status_code=status,
            headers=response_headers,
        )

    def sdk_error(self, status, error_type, *, headers=None):
        response = self.sdk_response(status, error_type, headers=headers)
        with patch(
            "resend.http_client_requests.requests.request",
            return_value=response,
        ):
            with self.assertRaises(ResendDeliveryError) as context:
                ResendProvider(api_key="re_test_only").send(**self.send_kwargs)
        return context.exception

    def test_provider_requires_api_key(self):
        with self.assertRaises(ResendConfigurationError):
            ResendProvider(api_key="")

    def test_installed_resend_contract_is_pinned_version(self):
        import resend

        self.assertEqual(metadata.version("resend"), "2.44.0")
        self.assertTrue(callable(resend.RequestsClient))
        self.assertTrue(callable(resend.Emails.send))
        self.assertTrue(hasattr(resend.exceptions.ResendError, "__init__"))

    @patch("notifications.email_providers.resend._load_resend")
    def test_provider_uses_reply_to_text_html_and_idempotency(self, load_resend):
        emails = SimpleNamespace(send=Mock(return_value={"id": "resend-id-1"}))
        requests_client = Mock(return_value=object())
        previous_api_key = object()
        previous_http_client = object()
        fake_resend = SimpleNamespace(
            api_key=previous_api_key,
            default_http_client=previous_http_client,
            Emails=emails,
            RequestsClient=requests_client,
        )
        load_resend.return_value = fake_resend

        provider = ResendProvider(api_key="re_test_only", timeout_seconds=13)
        provider_id = provider.send(**self.send_kwargs)

        self.assertEqual(provider_id, "resend-id-1")
        requests_client.assert_called_once_with(timeout=13)
        self.assertIs(fake_resend.api_key, previous_api_key)
        self.assertIs(fake_resend.default_http_client, previous_http_client)
        params = emails.send.call_args.args[0]
        options = emails.send.call_args.kwargs["options"]
        self.assertEqual(params["to"], ["user@example.com"])
        self.assertEqual(params["reply_to"], "destek@dertderman.com")
        self.assertEqual(params["html"], "<p>HTML</p>")
        self.assertEqual(params["text"], "TEXT")
        self.assertEqual(options["idempotency_key"], "dertderman/test-key")

    @patch("notifications.email_providers.resend._load_resend")
    def test_provider_restores_sdk_globals_after_exception(self, load_resend):
        previous_api_key = object()
        previous_http_client = object()
        fake_resend = SimpleNamespace(
            api_key=previous_api_key,
            default_http_client=previous_http_client,
            Emails=SimpleNamespace(send=Mock(side_effect=RuntimeError("private"))),
            RequestsClient=Mock(return_value=object()),
        )
        load_resend.return_value = fake_resend

        with self.assertRaises(ResendDeliveryError):
            ResendProvider(api_key="re_test_only").send(**self.send_kwargs)

        self.assertIs(fake_resend.api_key, previous_api_key)
        self.assertIs(fake_resend.default_http_client, previous_http_client)

    def test_explicit_timeout_reaches_real_sdk_transport(self):
        response = SimpleNamespace(
            content=b'{"id":"resend-id-real-sdk"}',
            status_code=200,
            headers={"content-type": "application/json"},
        )
        with patch(
            "resend.http_client_requests.requests.request",
            return_value=response,
        ) as request:
            provider_id = ResendProvider(
                api_key="re_test_only",
                timeout_seconds=7,
            ).send(**self.send_kwargs)

        self.assertEqual(provider_id, "resend-id-real-sdk")
        self.assertEqual(request.call_args.kwargs["timeout"], 7)
        self.assertEqual(
            request.call_args.kwargs["headers"]["Idempotency-Key"],
            "dertderman/test-key",
        )

    @patch("notifications.email_providers.resend._load_resend")
    def test_unknown_exception_is_retryable_ambiguous(self, load_resend):
        emails = SimpleNamespace(send=Mock(side_effect=RuntimeError("secret-ish payload")))
        load_resend.return_value = SimpleNamespace(
            api_key=None,
            default_http_client=None,
            Emails=emails,
            RequestsClient=Mock(return_value=object()),
        )

        provider = ResendProvider(api_key="re_test_only")

        with self.assertRaises(ResendDeliveryError) as context:
            provider.send(**self.send_kwargs)

        self.assertEqual(context.exception.code, "provider_transport_unknown")
        self.assertTrue(context.exception.retryable)
        self.assertTrue(context.exception.outcome_unknown)
        self.assertNotIn("secret-ish payload", str(context.exception))

    @patch("notifications.email_providers.resend._load_resend")
    def test_provider_classifies_builtin_timeout_as_ambiguous_retry(
        self,
        load_resend,
    ):
        emails = SimpleNamespace(
            send=Mock(side_effect=TimeoutError("socket detail"))
        )
        load_resend.return_value = SimpleNamespace(
            api_key=None,
            default_http_client=None,
            Emails=emails,
            RequestsClient=Mock(return_value=object()),
        )
        provider = ResendProvider(api_key="re_test_only")

        with self.assertRaises(ResendDeliveryError) as context:
            provider.send(**self.send_kwargs)

        self.assertEqual(context.exception.code, "provider_timeout")
        self.assertTrue(context.exception.retryable)
        self.assertTrue(context.exception.outcome_unknown)
        self.assertNotIn("socket detail", str(context.exception))

    def test_real_sdk_timeout_is_retryable_ambiguous(self):
        import requests

        with patch(
            "resend.http_client_requests.requests.request",
            side_effect=requests.exceptions.Timeout("private timeout detail"),
        ):
            with self.assertRaises(ResendDeliveryError) as context:
                ResendProvider(api_key="re_test_only").send(**self.send_kwargs)

        self.assertEqual(context.exception.code, "provider_timeout")
        self.assertTrue(context.exception.retryable)
        self.assertTrue(context.exception.outcome_unknown)

    def test_real_sdk_connection_error_is_retryable_ambiguous(self):
        import requests

        with patch(
            "resend.http_client_requests.requests.request",
            side_effect=requests.exceptions.ConnectionError("private connection detail"),
        ):
            with self.assertRaises(ResendDeliveryError) as context:
                ResendProvider(api_key="re_test_only").send(**self.send_kwargs)

        self.assertEqual(context.exception.code, "provider_connection_error")
        self.assertTrue(context.exception.retryable)
        self.assertTrue(context.exception.outcome_unknown)

    def test_400_is_permanent_invalid_request(self):
        error = self.sdk_error(400, "validation_error")
        self.assertEqual(error.code, "provider_invalid_request")
        self.assertFalse(error.retryable)
        self.assertFalse(error.outcome_unknown)

    def test_401_is_global_authentication_failure(self):
        error = self.sdk_error(401, "missing_api_key")
        self.assertEqual(error.code, "provider_authentication")
        self.assertFalse(error.retryable)
        self.assertFalse(error.outcome_unknown)
        self.assertTrue(error.global_problem)

    def test_403_is_global_authentication_failure(self):
        error = self.sdk_error(403, "invalid_api_key")
        self.assertEqual(error.code, "provider_authentication")
        self.assertFalse(error.retryable)
        self.assertFalse(error.outcome_unknown)
        self.assertTrue(error.global_problem)

    def test_404_is_permanent_invalid_request(self):
        error = self.sdk_error(404, "not_found")
        self.assertEqual(error.code, "provider_invalid_request")
        self.assertFalse(error.retryable)

    def test_422_is_permanent_invalid_request(self):
        error = self.sdk_error(422, "validation_error")
        self.assertEqual(error.code, "provider_invalid_request")
        self.assertFalse(error.retryable)
        self.assertFalse(error.outcome_unknown)

    def test_429_is_retryable_and_preserves_retry_after(self):
        error = self.sdk_error(
            429,
            "rate_limit_exceeded",
            headers={"Retry-After": "17"},
        )
        self.assertEqual(error.code, "provider_rate_limited")
        self.assertTrue(error.retryable)
        self.assertFalse(error.outcome_unknown)
        self.assertEqual(error.retry_after_seconds, 17)

    def test_500_is_retryable_server_error(self):
        error = self.sdk_error(500, "application_error")
        self.assertEqual(error.code, "provider_server_error")
        self.assertTrue(error.retryable)
        self.assertTrue(error.outcome_unknown)

    def test_503_is_retryable_server_error(self):
        error = self.sdk_error(503, "internal_server_error")
        self.assertEqual(error.code, "provider_server_error")
        self.assertTrue(error.retryable)
        self.assertTrue(error.outcome_unknown)

    def test_idempotency_payload_conflict_is_permanent(self):
        error = self.sdk_error(409, "invalid_idempotent_request")
        self.assertEqual(error.code, "provider_idempotency_conflict")
        self.assertFalse(error.retryable)
        self.assertFalse(error.outcome_unknown)

    def test_concurrent_idempotent_request_is_retryable(self):
        error = self.sdk_error(
            409,
            "concurrent_idempotent_requests",
            headers={"retry-after": "3"},
        )
        self.assertEqual(error.code, "provider_idempotency_in_progress")
        self.assertTrue(error.retryable)
        self.assertTrue(error.outcome_unknown)
        self.assertEqual(error.retry_after_seconds, 3)

    def test_unknown_409_uses_ambiguous_fallback(self):
        error = self.sdk_error(409, "unrecognized_conflict")
        self.assertEqual(error.code, "provider_transport_unknown")
        self.assertTrue(error.retryable)
        self.assertTrue(error.outcome_unknown)

    def test_missing_provider_message_id_is_invalid_response(self):
        emails = SimpleNamespace(send=Mock(return_value={"id": ""}))
        fake_resend = SimpleNamespace(
            api_key=None,
            default_http_client=None,
            Emails=emails,
            RequestsClient=Mock(return_value=object()),
        )
        with patch(
            "notifications.email_providers.resend._load_resend",
            return_value=fake_resend,
        ):
            with self.assertRaises(ResendDeliveryError) as context:
                ResendProvider(api_key="re_test_only").send(**self.send_kwargs)

        self.assertEqual(context.exception.code, "provider_invalid_response")

    def test_logs_exclude_provider_payload_and_message_content(self):
        sensitive_values = (
            "private-person@example.com",
            "PRIVATE EMAIL BODY",
            "re_private_api_key",
            "PRIVATE PROVIDER RESPONSE",
        )
        kwargs = {
            **self.send_kwargs,
            "recipient_email": sensitive_values[0],
            "html_body": sensitive_values[1],
        }
        response = self.sdk_response(
            400,
            "validation_error",
            message=f"{sensitive_values[2]} {sensitive_values[3]}",
        )
        with patch(
            "resend.http_client_requests.requests.request",
            return_value=response,
        ), self.assertLogs(
            "notifications.email_providers.resend",
            level="WARNING",
        ) as captured:
            with self.assertRaises(ResendDeliveryError):
                ResendProvider(api_key=sensitive_values[2]).send(**kwargs)

        log_output = " ".join(captured.output)
        for sensitive_value in sensitive_values:
            self.assertNotIn(sensitive_value, log_output)
