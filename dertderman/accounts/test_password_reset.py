from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import base36_to_int, urlsafe_base64_encode

from notifications.email_providers.resend import ResendDeliveryError
from notifications.models import EmailDelivery, EmailOutbox
from notifications.outbox_service import (
    OutboxBusinessCancellation,
    OutboxClaimLost,
    cancel_email_outbox_claim,
    claim_email_outbox,
    purge_cancelled_password_reset_noops,
    render_outbox_email,
    send_outbox_email,
)

from accounts.models import User
from accounts.password_reset import (
    PASSWORD_RESET_STATE_CHANGED,
    build_password_reset_request_state_hash,
    build_password_reset_url,
    password_reset_token_generator,
    request_password_reset,
)
from accounts.password_reset_views import GENERIC_RESET_MESSAGE


RESET_SETTINGS = {
    "EMAIL_SENDING_ENABLED": True,
    "EMAIL_PROVIDER": "resend",
    "RESEND_API_KEY": "re_test_only",
    "DEFAULT_FROM_EMAIL": "DertDerman <info@dertderman.com>",
    "EMAIL_REPLY_TO": "destek@dertderman.com",
    "SITE_BASE_URL": "https://dertderman.com",
    "PASSWORD_RESET_TIMEOUT": 300,
}


@override_settings(**RESET_SETTINGS)
class PasswordResetRequestAndConfirmTests(TestCase):
    password = "Granite!9284Ocean"

    def create_user(self, **overrides):
        data = {
            "username": "reset-user",
            "email": "reset-user@example.com",
            "password": self.password,
            "user_type": User.UserType.USER,
            "is_active": True,
            "is_verified": True,
        }
        data.update(overrides)
        return User.objects.create_user(**data)

    def reset_route(self, user, token=None, issued_at=None):
        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        token = token or password_reset_token_generator.make_token_at(
            user, issued_at or timezone.now()
        )
        return reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": uidb64, "token": token},
        )

    def post_reset(self, email, *, follow=False):
        return self.client.post(
            reverse("accounts:password_reset"), {"email": email}, follow=follow
        )

    def assert_request_has_no_inline_email_work(self, email):
        with (
            patch("notifications.email_service.send_email") as send_email,
            patch(
                "notifications.email_providers.resend.ResendProvider.send"
            ) as provider_send,
            patch("accounts.password_reset.render_to_string") as render,
            patch.object(
                password_reset_token_generator, "make_token_at"
            ) as make_token,
        ):
            response = self.post_reset(email)
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        send_email.assert_not_called()
        provider_send.assert_not_called()
        render.assert_not_called()
        make_token.assert_not_called()

    def test_eligible_request_enqueues_one_actionable_intent_only(self):
        user = self.create_user()
        self.assert_request_has_no_inline_email_work(user.email)

        outbox = EmailOutbox.objects.get()
        self.assertEqual(outbox.kind, EmailOutbox.Kind.PASSWORD_RESET)
        self.assertEqual(outbox.status, EmailOutbox.Status.PENDING)
        self.assertEqual(outbox.recipient_user, user)
        self.assertTrue(outbox.recipient_hash)
        self.assertTrue(outbox.request_state_hash)
        self.assertIsNotNone(outbox.token_issued_at)
        self.assertEqual(
            outbox.expires_at,
            outbox.token_issued_at + timedelta(seconds=300),
        )
        self.assertEqual(
            outbox.provider_idempotency_key, f"dertderman/email/{outbox.pk}"
        )
        self.assertEqual(EmailDelivery.objects.count(), 0)
        stored = [
            str(getattr(outbox, field.attname))
            for field in EmailOutbox._meta.concrete_fields
            if field.attname != "recipient_user_id"
        ]
        self.assertNotIn(user.email, stored)

    def test_unknown_email_enqueues_one_noop_with_same_public_result(self):
        submitted = "missing-person@example.com"
        self.assert_request_has_no_inline_email_work(submitted)

        outbox = EmailOutbox.objects.get()
        self.assertIsNone(outbox.recipient_user)
        self.assertEqual(outbox.recipient_hash, "")
        self.assertEqual(outbox.request_state_hash, "")
        self.assertIsNone(outbox.token_issued_at)
        self.assertIsNone(outbox.expires_at)
        self.assertEqual(EmailDelivery.objects.count(), 0)
        stored = [
            str(getattr(outbox, field.attname))
            for field in EmailOutbox._meta.concrete_fields
        ]
        self.assertNotIn(submitted, stored)
        done = self.client.get(reverse("accounts:password_reset_done"))
        self.assertContains(done, GENERIC_RESET_MESSAGE)

    def test_each_ineligible_account_enqueues_a_noop(self):
        cases = (
            {"username": "unverified", "email": "unverified@example.com", "is_verified": False},
            {"username": "inactive", "email": "inactive@example.com", "is_active": False},
            {"username": "company", "email": "company@example.com", "user_type": User.UserType.COMPANY},
            {"username": "admin", "email": "admin@example.com", "user_type": User.UserType.ADMIN},
        )
        for case in cases:
            user = self.create_user(**case)
            self.assert_request_has_no_inline_email_work(user.email)

        noops = EmailOutbox.objects.filter(recipient_user__isnull=True)
        self.assertEqual(noops.count(), len(cases))
        self.assertFalse(noops.exclude(recipient_hash="").exists())

    @override_settings(RESEND_API_KEY="", EMAIL_SENDING_ENABLED=False)
    def test_request_does_not_validate_provider_configuration(self):
        user = self.create_user()
        response = self.post_reset(user.email)
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(EmailOutbox.objects.count(), 1)

    def test_enqueue_exception_keeps_generic_response_and_sanitized_log(self):
        submitted = "private-reset-address@example.com"
        with (
            patch(
                "accounts.password_reset.EmailOutbox.objects.create",
                side_effect=RuntimeError(f"database detail {submitted}"),
            ),
            self.assertLogs("accounts.password_reset", level="ERROR") as logs,
        ):
            response = self.post_reset(submitted, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, GENERIC_RESET_MESSAGE)
        self.assertNotContains(response, "database detail")
        self.assertNotIn(submitted, "\n".join(logs.output))

    def test_request_state_is_keyed_and_changes_with_security_state(self):
        user = self.create_user()
        original = build_password_reset_request_state_hash(user)
        self.assertEqual(len(original), 64)
        self.assertNotEqual(original, user.password)
        user.is_verified = False
        self.assertNotEqual(original, build_password_reset_request_state_hash(user))

    def test_same_state_and_issue_time_produce_identical_token(self):
        user = self.create_user()
        issued_at = timezone.now().replace(microsecond=987654)
        first = password_reset_token_generator.make_token_at(user, issued_at)
        second = password_reset_token_generator.make_token_at(user, issued_at)
        self.assertEqual(first, second)

    def test_token_timestamp_uses_request_time_and_django_second_precision(self):
        user = self.create_user()
        issued_at = timezone.now() - timedelta(seconds=40)
        token = password_reset_token_generator.make_token_at(user, issued_at)
        timestamp = base36_to_int(token.split("-", 1)[0])
        expected_naive = issued_at.astimezone().replace(tzinfo=None)
        self.assertEqual(
            timestamp,
            password_reset_token_generator._num_seconds(expected_naive),
        )
        with patch.object(
            password_reset_token_generator,
            "_now",
            return_value=expected_naive + timedelta(seconds=59),
        ):
            self.assertTrue(password_reset_token_generator.check_token(user, token))
        with patch.object(
            password_reset_token_generator,
            "_now",
            return_value=expected_naive + timedelta(seconds=301),
        ):
            self.assertFalse(password_reset_token_generator.check_token(user, token))

    def test_worker_generated_token_is_accepted_by_confirm_view(self):
        user = self.create_user()
        route = self.reset_route(
            user, issued_at=timezone.now() - timedelta(seconds=10)
        )
        response = self.client.get(route)
        self.assertEqual(response.status_code, 302)
        form_page = self.client.get(response["Location"])
        self.assertTrue(form_page.context["validlink"])

    def test_valid_link_get_does_not_change_password(self):
        user = self.create_user()
        original_hash = user.password
        response = self.client.get(self.reset_route(user))
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.password, original_hash)

    def test_post_changes_password_without_login_and_token_is_single_use(self):
        user = self.create_user()
        route = self.reset_route(user)
        first = self.client.get(route)
        new_password = "Cedar!4719Galaxy"
        response = self.client.post(
            first["Location"],
            {"new_password1": new_password, "new_password2": new_password},
        )
        self.assertRedirects(response, reverse("accounts:password_reset_complete"))
        user.refresh_from_db()
        self.assertTrue(user.check_password(new_password))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(self.client.get(route).context["validlink"])

    def test_tampered_and_expired_tokens_are_rejected(self):
        user = self.create_user()
        token = password_reset_token_generator.make_token_at(user, timezone.now())
        self.assertFalse(
            self.client.get(self.reset_route(user, token=f"{token}x")).context[
                "validlink"
            ]
        )
        with self.settings(PASSWORD_RESET_TIMEOUT=-1):
            expired = self.client.get(self.reset_route(user))
        self.assertFalse(expired.context["validlink"])

    def test_security_state_and_eligibility_changes_invalidate_confirm_token(self):
        mutations = (
            ("password", lambda user: user.set_password("Changed!9384River")),
            ("last_login", lambda user: setattr(user, "last_login", timezone.now())),
            ("email", lambda user: setattr(user, "email", "changed@example.com")),
            ("inactive", lambda user: setattr(user, "is_active", False)),
            ("unverified", lambda user: setattr(user, "is_verified", False)),
            ("company", lambda user: setattr(user, "user_type", User.UserType.COMPANY)),
        )
        for index, (name, mutate) in enumerate(mutations):
            with self.subTest(state=name):
                user = self.create_user(
                    username=f"state-{index}", email=f"state-{index}@example.com"
                )
                route = self.reset_route(user)
                mutate(user)
                user.save()
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context["validlink"])

    def test_request_and_password_update_require_csrf(self):
        user = self.create_user()
        client = Client(enforce_csrf_checks=True)
        request_response = client.post(
            reverse("accounts:password_reset"), {"email": user.email}
        )
        self.assertEqual(request_response.status_code, 403)
        first = client.get(self.reset_route(user))
        update_response = client.post(
            first["Location"],
            {
                "new_password1": "Quartz!6591Forest",
                "new_password2": "Quartz!6591Forest",
            },
        )
        self.assertEqual(update_response.status_code, 403)
        user.refresh_from_db()
        self.assertTrue(user.check_password(self.password))

    def test_login_page_links_to_password_reset(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertContains(response, reverse("accounts:password_reset"))


@override_settings(**RESET_SETTINGS)
class PasswordResetWorkerTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        resend_loader = patch("notifications.outbox_service._load_resend")
        resend_loader.start().return_value = object()
        self.addCleanup(resend_loader.stop)
        self.sequence = 0

    def create_user(self):
        self.sequence += 1
        return User.objects.create_user(
            username=f"worker-{self.sequence}",
            email=f"worker-{self.sequence}@example.com",
            password="Granite!9284Ocean",
            user_type=User.UserType.USER,
            is_active=True,
            is_verified=True,
        )

    def enqueue(self, user=None):
        outbox = request_password_reset(
            user.email if user else "missing@example.com"
        )
        self.assertIsNotNone(outbox)
        return outbox

    def claim(self, outbox):
        claims = claim_email_outbox(batch_size=100)
        claim = next(item for item in claims if item.outbox_id == outbox.pk)
        outbox.refresh_from_db()
        return claim

    @patch("notifications.outbox_service._send_with_provider")
    def test_noop_is_cancelled_without_delivery_or_attempt(self, provider_send):
        outbox = self.enqueue()
        call_command("process_email_outbox", "--once")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.CANCELLED)
        self.assertEqual(outbox.last_error_code, "PASSWORD_RESET_NOOP")
        self.assertEqual(outbox.attempt_count, 0)
        self.assertIsNotNone(outbox.completed_at)
        self.assertFalse(EmailDelivery.objects.exists())
        provider_send.assert_not_called()

    @patch("notifications.outbox_service._send_with_provider", return_value="resend-1")
    def test_actionable_worker_sends_reset_url(self, provider_send):
        user = self.create_user()
        outbox = self.enqueue(user)
        call_command("process_email_outbox", "--once")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.SENT)
        payload = provider_send.call_args.args[1]
        self.assertIn("https://dertderman.com/hesap/sifre-sifirla/", payload.html_body)
        self.assertIn("https://dertderman.com/hesap/sifre-sifirla/", payload.text_body)

    @patch("notifications.outbox_service._send_with_provider")
    def test_retry_reuses_exact_payload_token_url_and_idempotency_key(self, provider_send):
        user = self.create_user()
        outbox = self.enqueue(user)
        first_claim = self.claim(outbox)
        first_payload = render_outbox_email(outbox)
        provider_send.side_effect = ResendDeliveryError(
            code="provider_timeout", retryable=True
        )
        first_result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=first_claim.claim_token,
            payload=first_payload,
        )
        EmailOutbox.objects.filter(pk=outbox.pk).update(available_at=timezone.now())
        second_claim = self.claim(outbox)
        second_payload = render_outbox_email(outbox)
        provider_send.side_effect = None
        provider_send.return_value = "resend-retry"
        second_result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=second_claim.claim_token,
            payload=second_payload,
        )
        self.assertEqual(first_payload, second_payload)
        self.assertEqual(first_result.idempotency_key, second_result.idempotency_key)
        self.assertEqual(first_result.status, "retry")
        self.assertEqual(second_result.status, "sent")
        outbox.refresh_from_db()
        self.assertEqual(outbox.attempt_count, 2)

    @patch("notifications.outbox_service._send_with_provider")
    def test_all_security_state_changes_cancel_before_provider(self, provider_send):
        mutations = (
            lambda user: user.set_password("Changed!9384River"),
            lambda user: setattr(user, "last_login", timezone.now()),
            lambda user: setattr(user, "email", f"changed-{user.pk}@example.com"),
            lambda user: setattr(user, "is_active", False),
            lambda user: setattr(user, "is_verified", False),
            lambda user: setattr(user, "user_type", User.UserType.COMPANY),
        )
        outboxes = []
        for mutate in mutations:
            user = self.create_user()
            outboxes.append(self.enqueue(user))
            mutate(user)
            user.save()
        call_command("process_email_outbox", "--once")
        for outbox in outboxes:
            outbox.refresh_from_db()
            self.assertEqual(outbox.status, EmailOutbox.Status.CANCELLED)
            self.assertEqual(outbox.last_error_code, PASSWORD_RESET_STATE_CHANGED)
            self.assertEqual(outbox.attempt_count, 0)
        self.assertFalse(EmailDelivery.objects.exists())
        provider_send.assert_not_called()

    @patch("notifications.outbox_service._send_with_provider")
    def test_expired_reset_is_cancelled_before_provider(self, provider_send):
        user = self.create_user()
        outbox = self.enqueue(user)
        EmailOutbox.objects.filter(pk=outbox.pk).update(expires_at=timezone.now())
        call_command("process_email_outbox", "--once")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.CANCELLED)
        self.assertEqual(outbox.last_error_code, "PASSWORD_RESET_EXPIRED")
        self.assertEqual(outbox.attempt_count, 0)
        provider_send.assert_not_called()

    def test_deleted_user_cascade_does_not_crash_worker(self):
        deleted_user = self.create_user()
        deleted_outbox = self.enqueue(deleted_user)
        claim = self.claim(deleted_outbox)
        deleted_user.delete()
        with self.assertRaises(OutboxBusinessCancellation) as cancellation:
            render_outbox_email(deleted_outbox)
        with self.assertRaises(OutboxClaimLost):
            cancel_email_outbox_claim(
                outbox_id=claim.outbox_id,
                claim_token=claim.claim_token,
                code=cancellation.exception.code,
            )
        survivor = self.enqueue(self.create_user())
        with patch(
            "notifications.outbox_service._send_with_provider",
            return_value="resend-survivor",
        ):
            call_command("process_email_outbox", "--once")
        survivor.refresh_from_db()
        self.assertEqual(survivor.status, EmailOutbox.Status.SENT)

    def test_stale_claim_cannot_cancel(self):
        outbox = self.enqueue()
        old_claim = self.claim(outbox)
        EmailOutbox.objects.filter(pk=outbox.pk).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1)
        )
        new_claim = self.claim(outbox)
        with self.assertRaises(OutboxClaimLost):
            cancel_email_outbox_claim(
                outbox_id=outbox.pk,
                claim_token=old_claim.claim_token,
                code="PASSWORD_RESET_NOOP",
            )
        cancel_email_outbox_claim(
            outbox_id=outbox.pk,
            claim_token=new_claim.claim_token,
            code="PASSWORD_RESET_NOOP",
        )

    def test_renderer_persists_no_plaintext_token_recipient_or_body(self):
        user = self.create_user()
        outbox = self.enqueue(user)
        self.claim(outbox)
        payload = render_outbox_email(outbox)
        reset_url, token = build_password_reset_url(
            user, issued_at=outbox.token_issued_at
        )
        outbox.refresh_from_db()
        stored = [
            str(getattr(outbox, field.attname))
            for field in EmailOutbox._meta.concrete_fields
            if field.attname != "recipient_user_id"
        ]
        serialized = "\n".join(stored)
        self.assertIn(reset_url, f"{payload.html_body}\n{payload.text_body}")
        self.assertNotIn(token, serialized)
        self.assertNotIn(payload.html_body, serialized)
        self.assertNotIn(payload.text_body, serialized)
        self.assertNotIn(user.email, stored)

    def test_noop_retention_cleanup_is_bounded_and_exact(self):
        old = timezone.now() - timedelta(hours=25)
        old_noops = [self.enqueue() for _index in range(3)]
        recent_noop = self.enqueue()
        for outbox in old_noops:
            EmailOutbox.objects.filter(pk=outbox.pk).update(
                status=EmailOutbox.Status.CANCELLED,
                completed_at=old,
            )
        EmailOutbox.objects.filter(pk=recent_noop.pk).update(
            status=EmailOutbox.Status.CANCELLED,
            completed_at=timezone.now(),
        )

        deleted = purge_cancelled_password_reset_noops(batch_size=2)

        self.assertEqual(deleted, 2)
        self.assertEqual(
            EmailOutbox.objects.filter(pk__in=[item.pk for item in old_noops]).count(),
            1,
        )
        self.assertTrue(EmailOutbox.objects.filter(pk=recent_noop.pk).exists())
