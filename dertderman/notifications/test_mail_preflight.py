import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.template import TemplateDoesNotExist, TemplateSyntaxError
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.models import User

from .email_service import build_recipient_hash
from .email_template_manifest import (
    DURABLE_EMAIL_TEMPLATE_MANIFEST,
    required_email_template_names,
)
from .models import EmailDelivery, EmailOutbox, Notification
from .outbox_service import (
    OUTBOX_RENDERERS,
    OutboxConfigurationError,
    validate_required_email_templates,
    validate_worker_configuration,
)


VALID_MAIL_SETTINGS = {
    "EMAIL_SENDING_ENABLED": True,
    "EMAIL_PROVIDER": "resend",
    "RESEND_API_KEY": "re_test_only",
    "RESEND_TIMEOUT_SECONDS": 30,
    "DEFAULT_FROM_EMAIL": "DertDerman <info@dertderman.com>",
    "EMAIL_REPLY_TO": "destek@dertderman.com",
    "SITE_BASE_URL": "https://dertderman.com",
    "IS_PRODUCTION": False,
}


@override_settings(**VALID_MAIL_SETTINGS)
class MailPreflightValidationTests(SimpleTestCase):
    def setUp(self):
        resend_loader = patch("notifications.outbox_service._load_resend")
        resend_loader.start().return_value = object()
        self.addCleanup(resend_loader.stop)

        template_loader = patch("notifications.outbox_service.get_template")
        self.get_template = template_loader.start()
        self.get_template.return_value = object()
        self.addCleanup(template_loader.stop)

    def test_required_template_manifest_is_exact(self):
        self.assertEqual(
            DURABLE_EMAIL_TEMPLATE_MANIFEST,
            {
                "PASSWORD_RESET": {
                    1: {
                        "html": "emails/password_reset.html",
                        "text": "emails/password_reset.txt",
                        "dependencies": ("emails/base.txt",),
                    },
                },
                "EMAIL_VERIFICATION": {
                    1: {
                        "html": "emails/email_verification.html",
                        "text": "emails/email_verification.txt",
                        "dependencies": (
                            "emails/base.html",
                            "emails/base.txt",
                        ),
                    },
                },
                "NOTIFICATION": {
                    1: {
                        "html": "emails/transactional_notification.html",
                        "text": "emails/transactional_notification.txt",
                        "dependencies": (),
                    },
                },
            },
        )

    def test_manifest_and_renderer_registry_cover_every_durable_kind(self):
        expected_kinds = set(EmailOutbox.Kind.values)
        self.assertEqual(set(DURABLE_EMAIL_TEMPLATE_MANIFEST), expected_kinds)
        self.assertEqual(set(OUTBOX_RENDERERS), expected_kinds)

    def test_preflight_loads_every_required_template(self):
        validate_required_email_templates()

        self.assertEqual(
            [call.args[0] for call in self.get_template.call_args_list],
            list(required_email_template_names()),
        )

    def assert_template_failure(self, template_name, error):
        def load_template(name):
            if name == template_name:
                raise error
            return object()

        self.get_template.side_effect = load_template
        with self.assertRaisesRegex(
            OutboxConfigurationError,
            "Required email templates are unavailable",
        ):
            validate_worker_configuration()

    def test_missing_html_template_fails_preflight(self):
        self.assert_template_failure(
            "emails/password_reset.html",
            TemplateDoesNotExist("private missing HTML path"),
        )

    def test_missing_text_template_fails_preflight(self):
        self.assert_template_failure(
            "emails/email_verification.txt",
            TemplateDoesNotExist("private missing text path"),
        )

    def test_missing_base_template_fails_preflight(self):
        self.assert_template_failure(
            "emails/base.html",
            TemplateDoesNotExist("private missing base path"),
        )

    def test_template_syntax_error_fails_preflight_without_detail(self):
        sensitive = "private template source {{ secret"
        self.get_template.side_effect = TemplateSyntaxError(sensitive)

        with self.assertRaises(OutboxConfigurationError) as captured:
            validate_worker_configuration()

        self.assertNotIn(sensitive, str(captured.exception))

    def test_other_template_compile_failure_is_sanitized(self):
        sensitive = "private backend parser detail"
        self.get_template.side_effect = RuntimeError(sensitive)

        with self.assertRaises(OutboxConfigurationError) as captured:
            validate_worker_configuration()

        self.assertNotIn(sensitive, str(captured.exception))

    def test_missing_default_from_email_fails_preflight(self):
        with self.settings(DEFAULT_FROM_EMAIL=""):
            with self.assertRaises(OutboxConfigurationError):
                validate_worker_configuration()

    def test_invalid_default_from_email_fails_preflight(self):
        for value in (
            "not-an-address",
            "sender",
            "first@example.com, second@example.com",
            "sender@example.com\r\nBcc: victim@example.com",
        ):
            with self.subTest(value=value), self.settings(DEFAULT_FROM_EMAIL=value):
                with self.assertRaises(OutboxConfigurationError):
                    validate_worker_configuration()

    def test_display_name_sender_is_accepted(self):
        validate_worker_configuration()

    def test_missing_reply_to_fails_preflight(self):
        with self.settings(EMAIL_REPLY_TO=""):
            with self.assertRaises(OutboxConfigurationError):
                validate_worker_configuration()

    def test_invalid_reply_to_fails_preflight(self):
        for value in (
            "reply-to",
            "one@example.com, two@example.com",
            "reply@example.com\nCc: victim@example.com",
        ):
            with self.subTest(value=value), self.settings(EMAIL_REPLY_TO=value):
                with self.assertRaises(OutboxConfigurationError):
                    validate_worker_configuration()

    def test_valid_reply_to_is_accepted(self):
        with self.settings(EMAIL_REPLY_TO="Support <destek@dertderman.com>"):
            validate_worker_configuration()

    def test_address_error_does_not_expose_raw_value(self):
        sensitive = "victim@example.com\r\nBcc: private@example.com"
        with self.settings(DEFAULT_FROM_EMAIL=sensitive):
            with self.assertRaises(OutboxConfigurationError) as captured:
                validate_worker_configuration()

        self.assertNotIn(sensitive, str(captured.exception))
        self.assertNotIn("private@example.com", str(captured.exception))

    def test_missing_site_base_url_fails_preflight(self):
        with self.settings(SITE_BASE_URL=""):
            with self.assertRaises(OutboxConfigurationError):
                validate_worker_configuration()

    def test_unsafe_site_base_urls_fail_preflight(self):
        invalid_urls = (
            "/relative",
            "javascript:alert(1)",
            "ftp://dertderman.com",
            "https://dertderman.invalid:bad-port",
            "https://-invalid-host.example",
            "https://dert derman.com",
            "https://user:secret@dertderman.com",
            "https://dertderman.com?token=secret",
            "https://dertderman.com#fragment",
            "https://dertderman.com/base",
        )
        for value in invalid_urls:
            with self.subTest(value=value), self.settings(SITE_BASE_URL=value):
                with self.assertRaises(OutboxConfigurationError):
                    validate_worker_configuration()

    def test_local_development_http_site_base_url_is_accepted(self):
        with self.settings(
            IS_PRODUCTION=False,
            SITE_BASE_URL="http://127.0.0.1:8000",
        ):
            validate_worker_configuration()

    def test_production_https_site_base_url_is_accepted(self):
        with self.settings(
            IS_PRODUCTION=True,
            SITE_BASE_URL="https://dertderman.com",
        ):
            validate_worker_configuration()

    def test_production_http_site_base_url_is_rejected(self):
        with self.settings(
            IS_PRODUCTION=True,
            SITE_BASE_URL="http://dertderman.com",
        ):
            with self.assertRaises(OutboxConfigurationError):
                validate_worker_configuration()

    def test_site_base_url_error_does_not_expose_raw_value(self):
        sensitive = "https://user:private@dertderman.com?token=secret"
        with self.settings(SITE_BASE_URL=sensitive):
            with self.assertRaises(OutboxConfigurationError) as captured:
                validate_worker_configuration()

        self.assertNotIn(sensitive, str(captured.exception))
        self.assertNotIn("private", str(captured.exception))

    def test_invalid_runtime_resend_timeout_fails_preflight(self):
        for value in (0, -1, 1.5, "30", True):
            with self.subTest(value=value), self.settings(
                RESEND_TIMEOUT_SECONDS=value
            ):
                with self.assertRaises(OutboxConfigurationError):
                    validate_worker_configuration()

    def test_positive_integer_runtime_resend_timeout_is_accepted(self):
        with self.settings(RESEND_TIMEOUT_SECONDS=1):
            validate_worker_configuration()

    def test_existing_provider_configuration_failures_are_preserved(self):
        invalid_settings = (
            {"EMAIL_SENDING_ENABLED": False},
            {"EMAIL_PROVIDER": "unsupported"},
            {"RESEND_API_KEY": ""},
        )
        for values in invalid_settings:
            with self.subTest(values=values), self.settings(**values):
                with self.assertRaises(OutboxConfigurationError):
                    validate_worker_configuration()


@override_settings(**VALID_MAIL_SETTINGS)
class MailPreflightWorkerTests(TransactionTestCase):
    def setUp(self):
        resend_loader = patch("notifications.outbox_service._load_resend")
        resend_loader.start().return_value = object()
        self.addCleanup(resend_loader.stop)

        self.user = User.objects.create_user(
            username="mail-preflight-user",
            email="mail-preflight@example.com",
            password="StrongRiver#9284",
            user_type=User.UserType.USER,
            is_active=True,
            is_verified=True,
        )

    def make_outbox(self):
        notification = Notification.objects.create(
            recipient_user=self.user,
            recipient_role=Notification.Scope.USER,
            notification_type=Notification.Type.PUBLISHED,
            event_key=f"mail-preflight:{uuid.uuid4()}",
            title="Mail preflight",
            message="Safe test content.",
        )
        return EmailOutbox.objects.create(
            kind=EmailOutbox.Kind.NOTIFICATION,
            recipient_user=self.user,
            notification=notification,
            recipient_hash=build_recipient_hash(self.user.email),
            provider="resend",
            provider_idempotency_key=f"dertderman/email/{uuid.uuid4()}",
            available_at=timezone.now() - timedelta(seconds=1),
        )

    @patch(
        "notifications.management.commands.process_email_outbox.claim_email_outbox"
    )
    @patch("notifications.outbox_service.get_template")
    def test_template_preflight_failure_happens_before_claim(
        self,
        get_template,
        claim,
    ):
        failures = (
            (
                "emails/password_reset.html",
                TemplateDoesNotExist("private HTML path"),
            ),
            (
                "emails/email_verification.txt",
                TemplateDoesNotExist("private text path"),
            ),
            ("emails/base.txt", TemplateDoesNotExist("private base path")),
            (
                "emails/transactional_notification.html",
                TemplateSyntaxError("private template source"),
            ),
        )
        for template_name, error in failures:
            with self.subTest(template_name=template_name):
                get_template.reset_mock()
                claim.reset_mock()

                def load_template(name):
                    if name == template_name:
                        raise error
                    return object()

                get_template.side_effect = load_template
                with self.assertRaises(CommandError):
                    call_command("process_email_outbox", once=True)
                claim.assert_not_called()

    @patch("notifications.outbox_service.get_template")
    def test_preflight_failure_leaves_queue_and_delivery_state_unchanged(
        self,
        get_template,
    ):
        get_template.side_effect = TemplateDoesNotExist("private template path")
        outbox = self.make_outbox()

        with self.assertRaises(CommandError):
            call_command("process_email_outbox", once=True)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.PENDING)
        self.assertIsNone(outbox.claim_token)
        self.assertEqual(outbox.attempt_count, 0)
        self.assertIsNone(outbox.first_attempt_at)
        self.assertFalse(EmailDelivery.objects.filter(outbox=outbox).exists())

    @patch("notifications.outbox_service.get_template")
    def test_startup_template_detail_is_not_exposed_or_persisted(self, get_template):
        sensitive = "private/template/path token=secret"
        get_template.side_effect = TemplateDoesNotExist(sensitive)
        outbox = self.make_outbox()

        with self.assertRaises(CommandError) as captured:
            call_command("process_email_outbox", once=True)

        outbox.refresh_from_db()
        self.assertNotIn(sensitive, str(captured.exception))
        self.assertNotIn("secret", str(captured.exception))
        self.assertEqual(outbox.last_error_code, "")

    def assert_runtime_template_failure(self, error):
        outbox = self.make_outbox()
        with (
            patch(
                "notifications.transactional_email.render_to_string",
                side_effect=error,
            ),
            patch("notifications.outbox_service._send_with_provider") as provider,
        ):
            with self.assertRaises(CommandError):
                call_command("process_email_outbox", once=True, batch_size=1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.RETRY)
        self.assertEqual(outbox.last_error_code, "WORKER_CONFIGURATION")
        self.assertNotEqual(outbox.last_error_code, "WORKER_UNEXPECTED_ERROR")
        self.assertEqual(outbox.attempt_count, 0)
        self.assertFalse(EmailDelivery.objects.filter(outbox=outbox).exists())
        provider.assert_not_called()

    def test_runtime_missing_template_uses_global_fail_fast(self):
        self.assert_runtime_template_failure(
            TemplateDoesNotExist("private runtime path")
        )

    def test_runtime_template_syntax_error_uses_global_fail_fast(self):
        self.assert_runtime_template_failure(
            TemplateSyntaxError("private runtime source")
        )
