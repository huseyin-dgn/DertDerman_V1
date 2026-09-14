from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.email_verification import (
    EMAIL_VERIFICATION_ALREADY_VERIFIED,
    EMAIL_VERIFICATION_STATE_CHANGED,
    EMAIL_VERIFICATION_USER_INELIGIBLE,
    build_email_verification_request_state_hash,
    build_email_verification_url,
    enqueue_email_verification,
    make_email_verification_token,
    render_email_verification_outbox,
    resolve_email_verification_token,
    send_verification_email,
)
from accounts.forms import UNVERIFIED_LOGIN_ERROR
from accounts.models import User
from notifications.email_providers.resend import ResendDeliveryError
from notifications.models import EmailDelivery, EmailOutbox
from notifications.outbox_service import (
    claim_email_outbox,
    render_outbox_email,
    send_outbox_email,
)


VERIFICATION_SETTINGS = {
    "EMAIL_SENDING_ENABLED": True,
    "EMAIL_PROVIDER": "resend",
    "RESEND_API_KEY": "re_test_only",
    "DEFAULT_FROM_EMAIL": "DertDerman <info@dertderman.com>",
    "EMAIL_REPLY_TO": "destek@dertderman.com",
    "SITE_BASE_URL": "https://dertderman.com",
    "EMAIL_VERIFICATION_TIMEOUT": 1800,
}


@override_settings(**VERIFICATION_SETTINGS)
class EmailVerificationTests(TestCase):
    password = "StrongRiver#9284Moon"

    def create_user(self, **overrides):
        data = {
            "username": "verify-user",
            "email": "verify-user@example.com",
            "password": self.password,
            "user_type": User.UserType.USER,
            "is_verified": False,
        }
        data.update(overrides)
        return User.objects.create_user(**data)

    def registration_data(self, **overrides):
        data = {
            "username": "new-verification-user",
            "email": "new-verification-user@example.com",
            "password1": self.password,
            "password2": self.password,
            "selected_avatar": "avatar-1",
        }
        data.update(overrides)
        return data

    def test_registration_atomically_creates_user_and_verification_outbox(self):
        response = self.client.post(
            reverse("accounts:register"),
            self.registration_data(),
        )

        self.assertRedirects(
            response,
            reverse("accounts:email_verification_pending"),
        )
        self.assertNotIn("_auth_user_id", self.client.session)

        user = User.objects.get(username="new-verification-user")
        self.assertFalse(user.is_verified)
        outbox = EmailOutbox.objects.get(recipient_user=user)
        self.assertEqual(outbox.kind, EmailOutbox.Kind.EMAIL_VERIFICATION)
        self.assertEqual(outbox.status, EmailOutbox.Status.PENDING)
        self.assertIsNone(outbox.notification)
        self.assertTrue(outbox.recipient_hash)
        self.assertTrue(outbox.request_state_hash)
        self.assertIsNotNone(outbox.token_issued_at)
        self.assertEqual(
            outbox.expires_at,
            outbox.token_issued_at + timedelta(seconds=1800),
        )
        self.assertEqual(
            outbox.provider_idempotency_key,
            f"dertderman/email/{outbox.pk}",
        )
        self.assertFalse(EmailDelivery.objects.exists())

    @patch(
        "accounts.email_verification.EmailOutbox.objects.create",
        side_effect=RuntimeError("private database detail"),
    )
    def test_enqueue_failure_rolls_back_user(self, _create):
        with self.assertLogs("accounts.views", level="ERROR") as logs:
            response = self.client.post(
                reverse("accounts:register"),
                self.registration_data(
                    username="rollback-user",
                    email="private-rollback@example.com",
                ),
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="rollback-user").exists())
        output = " ".join(logs.output)
        self.assertNotIn("private database detail", output)
        self.assertNotIn("private-rollback@example.com", output)

    def test_registration_request_does_not_render_or_call_provider(self):
        with (
            patch("accounts.email_verification.make_email_verification_token") as token,
            patch("accounts.email_verification.render_to_string") as render,
            patch(
                "notifications.email_providers.resend.ResendProvider.send"
            ) as provider_send,
        ):
            response = self.client.post(
                reverse("accounts:register"),
                self.registration_data(
                    username="no-inline-work",
                    email="no-inline-work@example.com",
                ),
            )

        self.assertRedirects(
            response,
            reverse("accounts:email_verification_pending"),
        )
        token.assert_not_called()
        render.assert_not_called()
        provider_send.assert_not_called()

    @override_settings(
        EMAIL_SENDING_ENABLED=False,
        EMAIL_PROVIDER="unsupported",
        RESEND_API_KEY="",
    )
    def test_invalid_provider_configuration_does_not_block_enqueue(self):
        response = self.client.post(
            reverse("accounts:register"),
            self.registration_data(
                username="provider-independent",
                email="provider-independent@example.com",
            ),
        )

        self.assertRedirects(
            response,
            reverse("accounts:email_verification_pending"),
        )
        self.assertTrue(
            EmailOutbox.objects.filter(
                recipient_user__username="provider-independent",
                kind=EmailOutbox.Kind.EMAIL_VERIFICATION,
            ).exists()
        )

    def test_outbox_persists_no_raw_token_recipient_or_body(self):
        user = self.create_user(username="private-outbox-user")
        outbox = enqueue_email_verification(user)
        token = make_email_verification_token(
            user,
            issued_at=outbox.token_issued_at,
        )
        payload = render_email_verification_outbox(outbox)
        stored = [
            str(getattr(outbox, field.attname))
            for field in EmailOutbox._meta.concrete_fields
            if field.attname != "recipient_user_id"
        ]
        serialized = "\n".join(stored)
        self.assertNotIn(user.email, serialized)
        self.assertNotIn(token, serialized)
        self.assertNotIn(payload.html_body, serialized)
        self.assertNotIn(payload.text_body, serialized)

    def test_verification_recipe_rejects_incomplete_intent(self):
        user = self.create_user(username="invalid-recipe")
        with self.assertRaises(IntegrityError), transaction.atomic():
            EmailOutbox.objects.create(
                kind=EmailOutbox.Kind.EMAIL_VERIFICATION,
                recipient_user=user,
                recipient_hash="",
                request_state_hash="",
                provider_idempotency_key="dertderman/email/invalid-recipe",
                available_at=timezone.now(),
            )

    def test_request_state_hash_is_keyed_and_tracks_security_state(self):
        user = self.create_user(username="state-hash")
        original = build_email_verification_request_state_hash(user)
        self.assertEqual(len(original), 64)
        self.assertNotEqual(original, user.password)
        user.is_active = False
        self.assertNotEqual(
            original,
            build_email_verification_request_state_hash(user),
        )

    def test_same_state_and_issue_time_produce_identical_token(self):
        user = self.create_user(username="deterministic-token")
        issued_at = timezone.now().replace(microsecond=987654)
        first = make_email_verification_token(user, issued_at=issued_at)
        second = make_email_verification_token(user, issued_at=issued_at)
        self.assertEqual(first, second)

    def test_legacy_and_fixed_timestamp_tokens_are_accepted(self):
        legacy_user = self.create_user(username="legacy-token")
        fixed_user = self.create_user(
            username="fixed-token",
            email="fixed-token@example.com",
        )
        legacy = make_email_verification_token(legacy_user)
        fixed = make_email_verification_token(
            fixed_user,
            issued_at=timezone.now(),
        )
        self.assertEqual(resolve_email_verification_token(legacy), legacy_user)
        self.assertEqual(resolve_email_verification_token(fixed), fixed_user)

    def test_unverified_user_cannot_login_even_with_correct_password(self):
        user = self.create_user()

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": user.username,
                "password": self.password,
            },
        )

        self.assertContains(response, UNVERIFIED_LOGIN_ERROR)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_verified_user_can_login(self):
        user = self.create_user(is_verified=True)

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": user.username,
                "password": self.password,
            },
        )

        self.assertRedirects(
        response,
        reverse("dashboard:home"),
    )

    def test_get_confirmation_page_never_verifies_account(self):
        user = self.create_user()
        token = make_email_verification_token(user)

        response = self.client.get(
            reverse(
                "accounts:email_verification_confirm",
                kwargs={"token": token},
            )
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.is_verified)
        self.assertContains(response, "E-postamı Doğrula")

    def test_post_confirmation_verifies_account(self):
        user = self.create_user()
        token = make_email_verification_token(user)
        route = reverse(
            "accounts:email_verification_confirm",
            kwargs={"token": token},
        )

        response = self.client.post(route)

        self.assertRedirects(response, reverse("accounts:login"))
        user.refresh_from_db()
        self.assertTrue(user.is_verified)

    def test_token_is_single_use(self):
        user = self.create_user()
        token = make_email_verification_token(user)
        route = reverse(
            "accounts:email_verification_confirm",
            kwargs={"token": token},
        )

        self.assertEqual(self.client.post(route).status_code, 302)
        self.assertEqual(self.client.get(route).status_code, 400)
        self.assertIsNone(resolve_email_verification_token(token))

    def test_tampered_token_is_rejected(self):
        user = self.create_user()
        token = make_email_verification_token(user)
        tampered = f"{token}x"

        response = self.client.get(
            reverse(
                "accounts:email_verification_confirm",
                kwargs={"token": tampered},
            )
        )

        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertFalse(user.is_verified)

    def test_expired_token_is_rejected(self):
        user = self.create_user()
        token = make_email_verification_token(
            user,
            issued_at=timezone.now() - timedelta(seconds=1801),
        )
        self.assertIsNone(resolve_email_verification_token(token))

    def test_email_and_password_changes_invalidate_token(self):
        mutations = (
            lambda user: setattr(user, "email", f"changed-{user.pk}@example.com"),
            lambda user: user.set_password("Changed!9284Password"),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                user = self.create_user(
                    username=f"changed-token-{index}",
                    email=f"changed-token-{index}@example.com",
                )
                token = make_email_verification_token(user)
                mutate(user)
                user.save()
                self.assertIsNone(resolve_email_verification_token(token))

    def test_verification_post_requires_csrf(self):
        user = self.create_user()
        token = make_email_verification_token(user)
        route = reverse(
            "accounts:email_verification_confirm",
            kwargs={"token": token},
        )

        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(route).status_code, 200)
        self.assertEqual(client.post(route).status_code, 403)

        user.refresh_from_db()
        self.assertFalse(user.is_verified)

    @override_settings(
        SITE_BASE_URL="https://dertderman.com",
        SUPPORT_EMAIL="destek@dertderman.com",
        SUPPORT_PHONE="+90 850 532 2206",
        SUPPORT_HOURS="Hafta içi 09:00 - 18:00",
    )
    @patch("accounts.email_verification.send_email")
    def test_email_uses_fixed_site_base_url_html_and_text(self, send_email):
        user = self.create_user()
        send_email.return_value = SimpleNamespace(status="sent")

        send_verification_email(user)

        kwargs = send_email.call_args.kwargs
        self.assertEqual(kwargs["recipient_email"], user.email)
        self.assertIn("https://dertderman.com/hesap/eposta-dogrula/", kwargs["html_body"])
        self.assertIn("https://dertderman.com/hesap/eposta-dogrula/", kwargs["text_body"])
        self.assertIn("DertDerman", kwargs["html_body"])
        self.assertIn("DertDerman", kwargs["text_body"])
        self.assertNotIn(user.email, kwargs["event_key"])


@override_settings(**VERIFICATION_SETTINGS)
class EmailVerificationWorkerTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        resend_loader = patch("notifications.outbox_service._load_resend")
        resend_loader.start().return_value = object()
        self.addCleanup(resend_loader.stop)
        self.sequence = 0

    def create_user(self):
        self.sequence += 1
        return User.objects.create_user(
            username=f"verification-worker-{self.sequence}",
            email=f"verification-worker-{self.sequence}@example.com",
            password="StrongRiver#9284Moon",
            user_type=User.UserType.USER,
            is_active=True,
            is_verified=False,
        )

    def enqueue(self, user=None):
        user = user or self.create_user()
        return user, enqueue_email_verification(user)

    def claim(self, outbox):
        claims = claim_email_outbox(batch_size=100)
        return next(claim for claim in claims if claim.outbox_id == outbox.pk)

    def assert_cancelled_after(self, mutate, expected_code):
        user, outbox = self.enqueue()
        mutate(user)
        user.save()
        with patch("notifications.outbox_service._send_with_provider") as provider:
            call_command("process_email_outbox", "--once")
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.CANCELLED)
        self.assertEqual(outbox.last_error_code, expected_code)
        self.assertEqual(outbox.attempt_count, 0)
        self.assertFalse(EmailDelivery.objects.exists())
        provider.assert_not_called()

    @patch(
        "notifications.outbox_service._send_with_provider",
        return_value="verification-message-id",
    )
    def test_worker_sends_verification_through_generic_pipeline(self, provider):
        _user, outbox = self.enqueue()

        call_command("process_email_outbox", "--once")

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.SENT)
        self.assertEqual(outbox.delivery.status, EmailDelivery.Status.SENT)
        self.assertEqual(
            outbox.delivery.provider_message_id,
            "verification-message-id",
        )
        payload = provider.call_args.args[1]
        self.assertIn("/hesap/eposta-dogrula/", payload.html_body)
        self.assertIn("/hesap/eposta-dogrula/", payload.text_body)

    def test_already_verified_is_cancelled_before_provider(self):
        self.assert_cancelled_after(
            lambda user: setattr(user, "is_verified", True),
            EMAIL_VERIFICATION_ALREADY_VERIFIED,
        )

    def test_changed_email_is_cancelled_before_provider(self):
        self.assert_cancelled_after(
            lambda user: setattr(user, "email", "changed-worker@example.com"),
            EMAIL_VERIFICATION_STATE_CHANGED,
        )

    def test_changed_password_is_cancelled_before_provider(self):
        self.assert_cancelled_after(
            lambda user: user.set_password("Changed!9284Password"),
            EMAIL_VERIFICATION_STATE_CHANGED,
        )

    def test_inactive_user_is_cancelled_before_provider(self):
        self.assert_cancelled_after(
            lambda user: setattr(user, "is_active", False),
            EMAIL_VERIFICATION_USER_INELIGIBLE,
        )

    def test_wrong_role_is_cancelled_before_provider(self):
        self.assert_cancelled_after(
            lambda user: setattr(user, "user_type", User.UserType.COMPANY),
            EMAIL_VERIFICATION_USER_INELIGIBLE,
        )

    def test_permanently_closed_user_is_cancelled_before_provider(self):
        self.assert_cancelled_after(
            lambda user: setattr(user, "is_permanently_closed", True),
            EMAIL_VERIFICATION_USER_INELIGIBLE,
        )

    @patch("notifications.outbox_service._send_with_provider")
    def test_expired_intent_is_cancelled_before_provider(self, provider):
        _user, outbox = self.enqueue()
        EmailOutbox.objects.filter(pk=outbox.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        call_command("process_email_outbox", "--once")

        outbox.refresh_from_db()
        self.assertEqual(outbox.status, EmailOutbox.Status.CANCELLED)
        self.assertEqual(outbox.last_error_code, "OUTBOX_EXPIRED")
        self.assertEqual(outbox.attempt_count, 0)
        provider.assert_not_called()

    @patch("notifications.outbox_service._send_with_provider")
    def test_retry_reuses_payload_token_hash_and_idempotency_key(self, provider):
        user, outbox = self.enqueue()
        first_claim = self.claim(outbox)
        first_payload = render_outbox_email(outbox)
        expected_url = build_email_verification_url(
            user,
            issued_at=outbox.token_issued_at,
        )
        provider.side_effect = ResendDeliveryError(
            code="provider_timeout",
            retryable=True,
            outcome_unknown=True,
        )

        first_result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=first_claim.claim_token,
            payload=first_payload,
        )
        outbox.refresh_from_db()
        first_payload_hash = outbox.payload_hash
        EmailOutbox.objects.filter(pk=outbox.pk).update(available_at=timezone.now())
        second_claim = self.claim(outbox)
        second_payload = render_outbox_email(outbox)
        provider.side_effect = None
        provider.return_value = "verification-retry-id"

        second_result = send_outbox_email(
            outbox_id=outbox.pk,
            claim_token=second_claim.claim_token,
            payload=second_payload,
        )

        self.assertEqual(first_result.status, "retry")
        self.assertEqual(second_result.status, "sent")
        self.assertEqual(first_payload, second_payload)
        self.assertIn(expected_url, first_payload.html_body)
        self.assertIn(expected_url, first_payload.text_body)
        self.assertEqual(
            first_result.idempotency_key,
            second_result.idempotency_key,
        )
        outbox.refresh_from_db()
        self.assertEqual(outbox.payload_hash, first_payload_hash)
        self.assertEqual(outbox.attempt_count, 2)

    def test_mutable_profile_name_does_not_change_payload(self):
        user, outbox = self.enqueue()
        first = render_email_verification_outbox(outbox)
        user.first_name = "Changed Name"
        user.save(update_fields=["first_name"])
        second = render_email_verification_outbox(outbox)
        self.assertEqual(first, second)

    def test_deleted_user_cascades_intent_without_provider_call(self):
        user, outbox = self.enqueue()
        outbox_id = outbox.pk
        user.delete()

        with patch("notifications.outbox_service._send_with_provider") as provider:
            call_command("process_email_outbox", "--once")

        self.assertFalse(EmailOutbox.objects.filter(pk=outbox_id).exists())
        provider.assert_not_called()
