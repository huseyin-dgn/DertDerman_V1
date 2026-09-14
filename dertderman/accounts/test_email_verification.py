from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.core.cache import cache
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.email_verification import (
    EMAIL_VERIFICATION_ALREADY_VERIFIED,
    EMAIL_VERIFICATION_STATE_CHANGED,
    EMAIL_VERIFICATION_USER_INELIGIBLE,
    build_email_verification_pending_resend_identity,
    build_email_verification_resend_identity,
    build_email_verification_request_state_hash,
    build_email_verification_url,
    enqueue_email_verification,
    make_email_verification_token,
    request_email_verification_resend,
    request_email_verification_resend_for_user_id,
    render_email_verification_outbox,
    resolve_email_verification_token,
    send_verification_email,
)
from accounts.forms import UNVERIFIED_LOGIN_ERROR
from accounts.models import User
from accounts.views import PENDING_EMAIL_VERIFICATION_USER_ID_SESSION_KEY
from notifications.email_providers.resend import ResendDeliveryError
from notifications.models import EmailDelivery, EmailOutbox
from notifications.outbox_service import (
    OUTBOX_UNSUPPORTED_TEMPLATE_VERSION,
    claim_email_outbox,
    render_outbox_email,
    send_outbox_email,
)
from core.rate_limit import RateLimitResult


VERIFICATION_SETTINGS = {
    "EMAIL_SENDING_ENABLED": True,
    "EMAIL_PROVIDER": "resend",
    "RESEND_API_KEY": "re_test_only",
    "DEFAULT_FROM_EMAIL": "DertDerman <info@dertderman.com>",
    "EMAIL_REPLY_TO": "destek@dertderman.com",
    "SITE_BASE_URL": "https://dertderman.com",
    "EMAIL_VERIFICATION_TIMEOUT": 1800,
    "EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS": 60,
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
        self.assertEqual(
            self.client.session[PENDING_EMAIL_VERIFICATION_USER_ID_SESSION_KEY],
            user.pk,
        )
        self.assertNotIn(user.email, str(dict(self.client.session)))
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
        self.assertNotIn(
            PENDING_EMAIL_VERIFICATION_USER_ID_SESSION_KEY,
            self.client.session,
        )
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
@override_settings(RATE_LIMIT_ENABLED=True)
class EmailVerificationResendTests(TestCase):
    password = "StrongRiver#9284Moon"

    def setUp(self):
        cache.clear()
        self.url = reverse("accounts:email_verification_resend")

    def create_user(self, **overrides):
        data = {
            "username": f"resend-user-{User.objects.count()}",
            "email": f"resend-{User.objects.count()}@example.com",
            "password": self.password,
            "user_type": User.UserType.USER,
            "is_active": True,
            "is_verified": False,
            "is_permanently_closed": False,
        }
        data.update(overrides)
        return User.objects.create_user(**data)

    def post(self, email, *, ip="127.0.0.70", client=None):
        return (client or self.client).post(
            self.url,
            {"email": email},
            REMOTE_ADDR=ip,
            follow=True,
        )

    def public_signature(self, response):
        return (
            response.status_code,
            response.redirect_chain,
            [str(message) for message in get_messages(response.wsgi_request)],
        )

    def test_account_states_have_identical_generic_public_response(self):
        eligible = self.create_user(
            username="resend-eligible",
            email="resend-eligible@example.com",
        )
        cases = (
            "unknown@example.com",
            eligible.email,
            self.create_user(
                username="resend-verified",
                email="resend-verified@example.com",
                is_verified=True,
            ).email,
            self.create_user(
                username="resend-inactive",
                email="resend-inactive@example.com",
                is_active=False,
            ).email,
            self.create_user(
                username="resend-company",
                email="resend-company@example.com",
                user_type=User.UserType.COMPANY,
            ).email,
            self.create_user(
                username="resend-closed",
                email="resend-closed@example.com",
                is_permanently_closed=True,
            ).email,
        )

        signatures = [
            self.public_signature(self.post(email, ip=f"127.0.1.{index + 1}"))
            for index, email in enumerate(cases)
        ]

        self.assertTrue(all(signature == signatures[0] for signature in signatures))
        self.assertIn("Eğer bu adres", signatures[0][2][0])
        self.assertEqual(
            EmailOutbox.objects.filter(
                kind=EmailOutbox.Kind.EMAIL_VERIFICATION
            ).count(),
            1,
        )

    def test_only_eligible_user_creates_verification_outbox(self):
        eligible = self.create_user(
            username="actionable-resend",
            email="actionable-resend@example.com",
        )
        self.post(eligible.email)
        outbox = EmailOutbox.objects.get(recipient_user=eligible)
        self.assertEqual(outbox.kind, EmailOutbox.Kind.EMAIL_VERIFICATION)
        self.assertEqual(outbox.status, EmailOutbox.Status.PENDING)
        self.assertEqual(
            outbox.provider_idempotency_key,
            f"dertderman/email/{outbox.pk}",
        )

    def test_unknown_and_ineligible_accounts_create_no_outbox(self):
        cases = (
            "missing@example.com",
            self.create_user(is_verified=True).email,
            self.create_user(is_active=False).email,
            self.create_user(user_type=User.UserType.COMPANY).email,
            self.create_user(is_permanently_closed=True).email,
        )
        for index, email in enumerate(cases):
            self.post(email, ip=f"127.0.2.{index + 1}")
        self.assertFalse(EmailOutbox.objects.exists())

    def test_unknown_email_is_not_persisted(self):
        submitted = "private-missing-person@example.com"
        self.post(submitted)
        self.assertFalse(EmailOutbox.objects.exists())
        self.assertNotIn(submitted, str(list(EmailOutbox.objects.values())))

    def test_request_path_does_not_generate_token_render_or_call_provider(self):
        user = self.create_user()
        with (
            patch("accounts.email_verification.make_email_verification_token") as token,
            patch("accounts.email_verification.render_to_string") as render,
            patch(
                "notifications.email_providers.resend.ResendProvider.send"
            ) as provider,
        ):
            self.post(user.email)
        token.assert_not_called()
        render.assert_not_called()
        provider.assert_not_called()

    def test_identity_rate_limit_allows_five_service_calls(self):
        with patch("accounts.views.request_email_verification_resend") as request:
            responses = [self.post("identity-limit@example.com") for _ in range(6)]
        self.assertEqual(request.call_count, 5)
        signatures = [self.public_signature(response) for response in responses]
        self.assertTrue(all(signature == signatures[0] for signature in signatures))

    def test_identity_rate_limited_request_creates_no_outbox(self):
        email = "becomes-eligible-after-limit@example.com"
        for _ in range(5):
            self.post(email)
        user = self.create_user(
            username="limited-before-eligible",
            email=email,
        )

        response = self.post(email)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(EmailOutbox.objects.filter(recipient_user=user).exists())

    def test_ip_rate_limit_allows_twenty_service_calls(self):
        with patch("accounts.views.request_email_verification_resend") as request:
            responses = [
                self.post(f"ip-limit-{index}@example.com", ip="127.0.0.81")
                for index in range(21)
            ]
        self.assertEqual(request.call_count, 20)
        signatures = [self.public_signature(response) for response in responses]
        self.assertTrue(all(signature == signatures[0] for signature in signatures))

    @patch("accounts.views.consume_rate_limit")
    def test_rate_limit_identity_is_keyed_hmac_not_raw_email(self, consume):
        consume.return_value = RateLimitResult(True, 1, 5, 0)
        submitted = "Private.Person@Example.COM"

        self.post(submitted)

        identity_call = next(
            call
            for call in consume.call_args_list
            if call.kwargs["scope"] == "email-verification-resend-identity"
        )
        identifier = identity_call.kwargs["identifier"]
        self.assertEqual(len(identifier), 64)
        self.assertNotEqual(identifier, submitted.casefold())
        self.assertEqual(
            identifier,
            build_email_verification_resend_identity(submitted),
        )

    def test_repeated_sequential_posts_create_one_active_intent(self):
        user = self.create_user()
        self.post(user.email)
        self.post(user.email)
        self.assertEqual(
            EmailOutbox.objects.filter(recipient_user=user).count(),
            1,
        )

    def test_resend_service_locks_user_row_before_rechecking(self):
        user = self.create_user()
        with patch.object(
            User.objects,
            "select_for_update",
            wraps=User.objects.select_for_update,
        ) as select_for_update:
            request_email_verification_resend(user.email)
        select_for_update.assert_called_once_with()
        self.assertEqual(EmailOutbox.objects.filter(recipient_user=user).count(), 1)

    def test_active_pending_retry_and_processing_intents_are_deduplicated(self):
        for status in (
            EmailOutbox.Status.PENDING,
            EmailOutbox.Status.RETRY,
            EmailOutbox.Status.PROCESSING,
        ):
            with self.subTest(status=status):
                user = self.create_user()
                outbox = enqueue_email_verification(user)
                if status == EmailOutbox.Status.RETRY:
                    EmailOutbox.objects.filter(pk=outbox.pk).update(status=status)
                elif status == EmailOutbox.Status.PROCESSING:
                    claim_email_outbox(batch_size=100)

                request_email_verification_resend(user.email)

                self.assertEqual(
                    EmailOutbox.objects.filter(recipient_user=user).count(),
                    1,
                )

    def test_expired_pending_does_not_block_new_intent(self):
        user = self.create_user()
        old = enqueue_email_verification(user)
        EmailOutbox.objects.filter(pk=old.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        request_email_verification_resend(user.email)
        self.assertEqual(EmailOutbox.objects.filter(recipient_user=user).count(), 2)

    def test_dead_and_cancelled_intents_do_not_block_new_intent(self):
        for status in (EmailOutbox.Status.DEAD, EmailOutbox.Status.CANCELLED):
            with self.subTest(status=status):
                user = self.create_user()
                old = enqueue_email_verification(user)
                EmailOutbox.objects.filter(pk=old.pk).update(
                    status=status,
                    completed_at=timezone.now(),
                )
                request_email_verification_resend(user.email)
                self.assertEqual(
                    EmailOutbox.objects.filter(recipient_user=user).count(),
                    2,
                )

    def test_recent_sent_intent_enforces_cooldown(self):
        user = self.create_user()
        sent = enqueue_email_verification(user)
        EmailOutbox.objects.filter(pk=sent.pk).update(
            status=EmailOutbox.Status.SENT,
            completed_at=timezone.now(),
        )
        request_email_verification_resend(user.email)
        self.assertEqual(EmailOutbox.objects.filter(recipient_user=user).count(), 1)

    def test_sent_intent_older_than_cooldown_allows_new_intent(self):
        user = self.create_user()
        sent = enqueue_email_verification(user)
        EmailOutbox.objects.filter(pk=sent.pk).update(
            status=EmailOutbox.Status.SENT,
            completed_at=timezone.now() - timedelta(seconds=61),
        )
        request_email_verification_resend(user.email)
        self.assertEqual(EmailOutbox.objects.filter(recipient_user=user).count(), 2)

    @patch(
        "accounts.email_verification.enqueue_email_verification",
        side_effect=RuntimeError("private database detail"),
    )
    def test_enqueue_failure_keeps_generic_response_and_sanitized_log(self, _enqueue):
        user = self.create_user(email="private-enqueue@example.com")
        with self.assertLogs("accounts.email_verification", level="ERROR") as logs:
            response = self.post(user.email)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Eğer bu adres", self.public_signature(response)[2][0])
        output = " ".join(logs.output)
        self.assertNotIn(user.email, output)
        self.assertNotIn("private database detail", output)

    def test_endpoint_requires_post_and_csrf(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(self.url, {"email": "csrf@example.com"})
        self.assertEqual(response.status_code, 403)


@override_settings(**VERIFICATION_SETTINGS)
@override_settings(RATE_LIMIT_ENABLED=True)
class EmailVerificationPendingResendTests(TestCase):
    password = "StrongRiver#9284Moon"

    def setUp(self):
        cache.clear()
        self.url = reverse("accounts:email_verification_resend_current")

    def create_user(self, **overrides):
        index = User.objects.count()
        data = {
            "username": f"pending-resend-{index}",
            "email": f"pending-resend-{index}@example.com",
            "password": self.password,
            "user_type": User.UserType.USER,
            "is_active": True,
            "is_verified": False,
            "is_permanently_closed": False,
        }
        data.update(overrides)
        return User.objects.create_user(**data)

    def set_pending_user(self, user_id, *, client=None):
        client = client or self.client
        session = client.session
        session[PENDING_EMAIL_VERIFICATION_USER_ID_SESSION_KEY] = user_id
        session.save()

    def post(self, *, data=None, ip="127.0.3.1", client=None):
        return (client or self.client).post(
            self.url,
            data or {},
            REMOTE_ADDR=ip,
            follow=True,
        )

    def public_signature(self, response):
        return (
            response.status_code,
            response.redirect_chain,
            [str(message) for message in get_messages(response.wsgi_request)],
        )

    def test_pending_page_has_button_without_email_field(self):
        response = self.client.get(
            reverse("accounts:email_verification_pending")
        )
        self.assertContains(response, "Doğrulama e-postasını tekrar gönder")
        self.assertContains(response, f'action="{self.url}"')
        self.assertContains(response, 'method="post"')
        self.assertNotContains(response, 'name="email"')
        self.assertNotContains(response, 'type="email"')

    def test_endpoint_requires_post_and_csrf(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        self.set_pending_user(1, client=csrf_client)
        self.assertEqual(csrf_client.post(self.url).status_code, 403)

    def test_session_bound_resend_creates_outbox_for_current_user(self):
        user = self.create_user()
        self.set_pending_user(user.pk)

        response = self.post()

        self.assertEqual(response.status_code, 200)
        outbox = EmailOutbox.objects.get(recipient_user=user)
        self.assertEqual(outbox.kind, EmailOutbox.Kind.EMAIL_VERIFICATION)
        self.assertEqual(outbox.status, EmailOutbox.Status.PENDING)

    def test_request_body_cannot_select_another_user_or_email(self):
        current_user = self.create_user()
        other_user = self.create_user()
        self.set_pending_user(current_user.pk)

        self.post(
            data={
                "user_id": other_user.pk,
                "email": other_user.email,
            }
        )

        self.assertTrue(
            EmailOutbox.objects.filter(recipient_user=current_user).exists()
        )
        self.assertFalse(
            EmailOutbox.objects.filter(recipient_user=other_user).exists()
        )

    def test_missing_invalid_and_ineligible_sessions_are_generic_noops(self):
        cases = [
            None,
            "invalid-user-id",
            self.create_user(is_verified=True).pk,
            self.create_user(is_active=False).pk,
            self.create_user(user_type=User.UserType.COMPANY).pk,
            self.create_user(is_permanently_closed=True).pk,
        ]
        signatures = []
        for index, user_id in enumerate(cases):
            if user_id is None:
                self.client.session.flush()
            else:
                self.set_pending_user(user_id)
            signatures.append(
                self.public_signature(self.post(ip=f"127.0.4.{index + 1}"))
            )

        self.assertTrue(all(item == signatures[0] for item in signatures))
        self.assertFalse(EmailOutbox.objects.exists())

    def test_active_intents_are_deduplicated(self):
        for status in (
            EmailOutbox.Status.PENDING,
            EmailOutbox.Status.RETRY,
            EmailOutbox.Status.PROCESSING,
        ):
            with self.subTest(status=status):
                user = self.create_user()
                outbox = enqueue_email_verification(user)
                if status == EmailOutbox.Status.RETRY:
                    EmailOutbox.objects.filter(pk=outbox.pk).update(status=status)
                elif status == EmailOutbox.Status.PROCESSING:
                    claim_email_outbox(batch_size=100)
                self.set_pending_user(user.pk)

                self.post(ip=f"127.0.5.{user.pk}")

                self.assertEqual(
                    EmailOutbox.objects.filter(recipient_user=user).count(),
                    1,
                )

    def test_recent_sent_intent_enforces_cooldown(self):
        user = self.create_user()
        sent = enqueue_email_verification(user)
        EmailOutbox.objects.filter(pk=sent.pk).update(
            status=EmailOutbox.Status.SENT,
            completed_at=timezone.now(),
        )
        self.set_pending_user(user.pk)

        self.post()

        self.assertEqual(EmailOutbox.objects.filter(recipient_user=user).count(), 1)

    def test_sent_intent_older_than_cooldown_allows_new_intent(self):
        user = self.create_user()
        sent = enqueue_email_verification(user)
        EmailOutbox.objects.filter(pk=sent.pk).update(
            status=EmailOutbox.Status.SENT,
            completed_at=timezone.now() - timedelta(seconds=61),
        )
        self.set_pending_user(user.pk)

        self.post()

        self.assertEqual(EmailOutbox.objects.filter(recipient_user=user).count(), 2)

    def test_account_identity_limit_allows_five_service_calls(self):
        self.set_pending_user(7001)
        with patch(
            "accounts.views.request_email_verification_resend_for_user_id"
        ) as request:
            responses = [self.post() for _ in range(6)]

        self.assertEqual(request.call_count, 5)
        signatures = [self.public_signature(response) for response in responses]
        self.assertTrue(all(item == signatures[0] for item in signatures))

    def test_ip_limit_allows_twenty_service_calls(self):
        with patch(
            "accounts.views.request_email_verification_resend_for_user_id"
        ) as request:
            responses = []
            for user_id in range(8001, 8022):
                self.set_pending_user(user_id)
                responses.append(self.post(ip="127.0.6.1"))

        self.assertEqual(request.call_count, 20)
        signatures = [self.public_signature(response) for response in responses]
        self.assertTrue(all(item == signatures[0] for item in signatures))

    @patch("accounts.views.consume_rate_limit")
    def test_account_rate_limit_identity_is_keyed_user_id_hmac(self, consume):
        consume.return_value = RateLimitResult(True, 1, 5, 0)
        user = self.create_user()
        self.set_pending_user(user.pk)

        self.post()

        identity_call = next(
            call
            for call in consume.call_args_list
            if call.kwargs["scope"]
            == "email-verification-pending-resend-identity"
        )
        identifier = identity_call.kwargs["identifier"]
        self.assertEqual(len(identifier), 64)
        self.assertNotEqual(identifier, str(user.pk))
        self.assertEqual(
            identifier,
            build_email_verification_pending_resend_identity(user.pk),
        )

    def test_request_path_does_not_generate_token_render_or_call_provider(self):
        user = self.create_user()
        self.set_pending_user(user.pk)
        with (
            patch("accounts.email_verification.make_email_verification_token") as token,
            patch("accounts.email_verification.render_to_string") as render,
            patch(
                "notifications.email_providers.resend.ResendProvider.send"
            ) as provider,
        ):
            self.post()

        token.assert_not_called()
        render.assert_not_called()
        provider.assert_not_called()

    def test_session_resend_service_locks_user_row(self):
        user = self.create_user()
        with patch.object(
            User.objects,
            "select_for_update",
            wraps=User.objects.select_for_update,
        ) as select_for_update:
            request_email_verification_resend_for_user_id(user.pk)

        select_for_update.assert_called_once_with()
        self.assertEqual(EmailOutbox.objects.filter(recipient_user=user).count(), 1)

    def test_successful_verification_clears_matching_pending_session(self):
        user = self.create_user()
        self.set_pending_user(user.pk)
        token = make_email_verification_token(user)

        self.client.post(
            reverse(
                "accounts:email_verification_confirm",
                kwargs={"token": token},
            )
        )

        self.assertNotIn(
            PENDING_EMAIL_VERIFICATION_USER_ID_SESSION_KEY,
            self.client.session,
        )

    def test_successful_verification_preserves_other_pending_session(self):
        verified_user = self.create_user()
        other_user = self.create_user()
        self.set_pending_user(other_user.pk)
        token = make_email_verification_token(verified_user)

        self.client.post(
            reverse(
                "accounts:email_verification_confirm",
                kwargs={"token": token},
            )
        )

        self.assertEqual(
            self.client.session[PENDING_EMAIL_VERIFICATION_USER_ID_SESSION_KEY],
            other_user.pk,
        )


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

    @patch("notifications.outbox_service._send_with_provider")
    def test_unsupported_template_version_is_dead_without_attempt(self, provider):
        _user, outbox = self.enqueue()
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
        provider.assert_not_called()

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
