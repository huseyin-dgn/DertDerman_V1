from datetime import timedelta
from unittest.mock import patch

from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from companies.models import Company
from complaints.models import (
    Complaint,
    ComplaintComment,
    ComplaintLike,
    ComplaintReaction,
    CompanyReport,
    ContentReport,
    UserReport,
)
from notifications.models import EmailOutbox

from .email_change import apply_email_change_token, make_email_change_token
from .email_verification import (
    make_email_verification_token,
    resolve_email_verification_token,
)
from .forms import (
    PERMANENTLY_CLOSED_LOGIN_ERROR,
    USER_LOGIN_ERROR,
    RegisterForm,
)
from .models import User
from .password_reset import password_reset_token_generator, request_password_reset


PASSWORD = "ProductionHardening2026!"


class SuspendedAccountBoundaryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="suspended-user",
            email="suspended-user@example.com",
            password=PASSWORD,
            user_type=User.UserType.USER,
            is_verified=True,
        )
        self.other = User.objects.create_user(
            username="report-target",
            email="report-target@example.com",
            password=PASSWORD,
            user_type=User.UserType.USER,
            is_verified=True,
        )
        self.company = Company.objects.create(
            name="Suspension Boundary Company",
            is_active=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )
        self.complaint = Complaint.objects.create(
            user=self.other,
            company=self.company,
            title="Public suspension boundary complaint",
            description="A public complaint used to verify suspended writes.",
            status=Complaint.Status.PUBLISHED,
        )
        self.client.force_login(self.user)
        User.objects.filter(pk=self.user.pk).update(
            is_suspended=True,
            suspended_at=timezone.now(),
        )

    def test_stale_session_can_post_logout_and_is_invalidated(self):
        old_session_key = self.client.session.session_key
        self.assertTrue(Session.objects.filter(session_key=old_session_key).exists())

        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("core:home"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(
            Session.objects.filter(session_key=old_session_key).exists()
        )

    @patch("accounts.email_change_views.send_email_change_verification")
    def test_stale_session_keeps_reads_but_all_user_writes_fail_closed(
        self,
        send_verification,
    ):
        self.assertEqual(self.client.get(reverse("accounts:profile")).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 200)
        self.assertIn("_auth_user_id", self.client.session)

        mutation_requests = (
            (
                reverse("accounts:profile_edit"),
                {"first_name": "Blocked", "selected_avatar": "avatar-1"},
            ),
            (
                reverse("accounts:password_change"),
                {
                    "old_password": PASSWORD,
                    "new_password1": "ChangedProduction2027!",
                    "new_password2": "ChangedProduction2027!",
                },
            ),
            (
                reverse("accounts:email_change"),
                {
                    "current_password": PASSWORD,
                    "new_email": "blocked-change@example.com",
                },
            ),
            (reverse("complaints:like_toggle", args=[self.complaint.pk]), {}),
            (
                reverse("complaints:react", args=[self.complaint.pk]),
                {"reaction_type": "\U0001f44d"},
            ),
            (
                reverse("complaints:comment_create", args=[self.complaint.pk]),
                {"body": "This comment must not be created."},
            ),
            (
                reverse("complaints:report", args=[self.complaint.pk]),
                {"reason": "SPAM"},
            ),
            (
                reverse("complaints:user_report", args=[self.other.pk]),
                {"reason": "SPAM"},
            ),
            (
                reverse(
                    "companies_public:company_report",
                    args=[self.company.slug],
                ),
                {"reason": "FRAUD"},
            ),
            (
                reverse("complaints:create"),
                {
                    "company": self.company.pk,
                    "title": "Blocked complaint",
                    "description": "This complaint must never be created.",
                },
            ),
        )
        for url, data in mutation_requests:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data).status_code, 403)

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "")
        self.assertEqual(self.user.email, "suspended-user@example.com")
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertFalse(ComplaintLike.objects.exists())
        self.assertFalse(ComplaintReaction.objects.exists())
        self.assertFalse(ComplaintComment.objects.exists())
        self.assertFalse(ContentReport.objects.exists())
        self.assertFalse(UserReport.objects.exists())
        self.assertFalse(CompanyReport.objects.exists())
        self.assertEqual(Complaint.objects.count(), 1)
        send_verification.assert_not_called()

    def test_expired_suspension_does_not_block_profile_mutation(self):
        User.objects.filter(pk=self.user.pk).update(
            suspended_until=timezone.now() - timedelta(seconds=1)
        )
        response = self.client.post(
            reverse("accounts:profile_edit"),
            {"first_name": "Allowed", "selected_avatar": "avatar-1"},
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Allowed")

    def test_security_tokens_become_ineligible_during_suspension(self):
        user = User.objects.get(pk=self.user.pk)
        User.objects.filter(pk=user.pk).update(is_suspended=False, suspended_at=None)
        user.refresh_from_db()
        verification_user = User.objects.create_user(
            username="suspended-verification",
            email="suspended-verification@example.com",
            password=PASSWORD,
            user_type=User.UserType.USER,
            is_verified=False,
        )
        verification_token = make_email_verification_token(verification_user)
        email_change_token = make_email_change_token(
            user,
            "suspended-new@example.com",
        )
        reset_token = password_reset_token_generator.make_token(user)

        User.objects.filter(pk__in=(user.pk, verification_user.pk)).update(
            is_suspended=True,
            suspended_at=timezone.now(),
        )

        verification_user.refresh_from_db()
        user.refresh_from_db()
        self.assertIsNone(resolve_email_verification_token(verification_token))
        self.assertIsNone(apply_email_change_token(email_change_token))
        self.assertFalse(password_reset_token_generator.check_token(user, reset_token))
        self.assertIsNone(request_password_reset(user.email).recipient_user)


class PermanentClosureLifecycleTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="closure-admin",
            email="closure-admin@example.com",
            password=PASSWORD,
            user_type=User.UserType.ADMIN,
        )
        self.user = User.objects.create_user(
            username="closure-target",
            email="closure-target@example.com",
            password=PASSWORD,
            user_type=User.UserType.USER,
            is_verified=True,
        )
        self.company = Company.objects.create(name="Closure Company")
        self.complaint = Complaint.objects.create(
            user=self.user,
            company=self.company,
            title="Complaint removed by closure",
            description="This record must be retained but removed from public access.",
            status=Complaint.Status.PUBLISHED,
        )

    @patch("adminx.permanent_closure.false_report_category_counts")
    @patch("adminx.permanent_closure.permanent_close_eligible", return_value=True)
    def test_closure_is_terminal_and_revokes_an_existing_session(
        self,
        _eligible,
        category_counts,
    ):
        category_counts.return_value = {
            "user_report": 4,
            "content_report": 0,
            "company_report": 0,
        }
        user_client = Client()
        user_client.force_login(self.user)
        old_session_key = user_client.session.session_key
        admin_client = Client()
        admin_client.force_login(self.admin)

        with self.captureOnCommitCallbacks(execute=True):
            response = admin_client.post(
                reverse("adminx:permanently_close_user", args=[self.user.pk]),
                {
                    "confirm_username": self.user.username,
                    "reason": "Confirmed repeated malicious reporting.",
                },
            )

        self.assertRedirects(
            response,
            reverse("adminx:user_detail", args=[self.user.pk]),
        )
        self.user.refresh_from_db()
        self.complaint.refresh_from_db()
        self.assertTrue(self.user.is_permanently_closed)
        self.assertFalse(self.user.is_active)
        self.assertIsNotNone(self.user.permanently_closed_at)
        self.assertEqual(self.complaint.status, Complaint.Status.REMOVED)
        self.assertTrue(self.complaint.removed_for_violation)
        self.assertFalse(Session.objects.filter(session_key=old_session_key).exists())

        user_client.cookies["sessionid"] = old_session_key
        private_response = user_client.get(reverse("accounts:profile"))
        self.assertRedirects(
            private_response,
            f'{reverse("accounts:login")}?next={reverse("accounts:profile")}',
            fetch_redirect_response=False,
        )
        self.assertEqual(
            Client().get(
                reverse("accounts:public_profile", args=[self.user.username])
            ).status_code,
            404,
        )
        self.assertIsNone(request_password_reset(self.user.email).recipient_user)

        login_client = Client()
        known_credentials = login_client.post(
            reverse("accounts:login"),
            {"username": self.user.username, "password": PASSWORD},
        )
        self.assertContains(known_credentials, PERMANENTLY_CLOSED_LOGIN_ERROR)
        self.assertNotIn("_auth_user_id", login_client.session)

    def test_wrong_password_does_not_reveal_permanent_closure(self):
        User.objects.filter(pk=self.user.pk).update(
            is_permanently_closed=True,
            is_active=False,
        )
        response = self.client.post(
            reverse("accounts:login"),
            {"username": self.user.username, "password": "wrong-password"},
        )
        self.assertContains(response, USER_LOGIN_ERROR)
        self.assertNotContains(response, PERMANENTLY_CLOSED_LOGIN_ERROR)

    def test_closed_login_check_does_not_mutate_the_password_hash(self):
        User.objects.filter(pk=self.user.pk).update(
            is_permanently_closed=True,
            is_active=False,
        )
        original_hash = User.objects.values_list("password", flat=True).get(
            pk=self.user.pk
        )
        response = self.client.post(
            reverse("accounts:login"),
            {"username": self.user.username, "password": PASSWORD},
        )
        self.assertContains(response, PERMANENTLY_CLOSED_LOGIN_ERROR)
        self.assertEqual(
            User.objects.values_list("password", flat=True).get(pk=self.user.pk),
            original_hash,
        )

    def test_case_variant_username_does_not_leak_another_accounts_state(self):
        User.objects.filter(pk=self.user.pk).update(
            username="CaseVariant",
            is_permanently_closed=True,
            is_active=False,
        )
        active = User.objects.create_user(
            username="casevariant",
            email="case-variant-active@example.com",
            password=PASSWORD,
            user_type=User.UserType.USER,
            is_verified=True,
        )
        response = self.client.post(
            reverse("accounts:login"),
            {"username": active.username, "password": PASSWORD},
        )
        self.assertRedirects(response, reverse("dashboard:home"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), active.pk)

    def test_suspend_and_restore_cannot_mutate_a_closed_account(self):
        User.objects.filter(pk=self.user.pk).update(
            is_permanently_closed=True,
            is_active=False,
            is_suspended=True,
            suspended_at=timezone.now(),
            suspension_reason="Historical suspension",
        )
        self.client.force_login(self.admin)
        for route in ("adminx:user_suspend", "adminx:user_unsuspend"):
            with self.subTest(route=route):
                response = self.client.post(reverse(route, args=[self.user.pk]))
                self.assertRedirects(
                    response,
                    reverse("adminx:user_detail", args=[self.user.pk]),
                )
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_permanently_closed)
        self.assertFalse(self.user.is_active)
        self.assertTrue(self.user.is_suspended)
        self.assertEqual(self.user.suspension_reason, "Historical suspension")


class AccountCredentialHardeningTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="credential-user",
            email="Credential.User@example.com",
            password=PASSWORD,
            user_type=User.UserType.USER,
            is_verified=True,
        )

    def test_database_enforces_case_insensitive_email_uniqueness(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(
                username="case-variant",
                email="credential.user@EXAMPLE.COM",
                password=PASSWORD,
            )

    def test_registration_does_not_disclose_closed_email_state(self):
        closed = User.objects.create_user(
            username="closed-email-owner",
            email="closed-email@example.com",
            password=PASSWORD,
            is_permanently_closed=True,
            is_active=False,
        )
        form_data = {
            "username": "registration-probe",
            "password1": PASSWORD,
            "password2": PASSWORD,
            "selected_avatar": "avatar-1",
        }
        closed_form = RegisterForm(data={**form_data, "email": closed.email})
        active_form = RegisterForm(data={**form_data, "email": self.user.email})
        self.assertFalse(closed_form.is_valid())
        self.assertFalse(active_form.is_valid())
        self.assertEqual(closed_form.errors["email"], active_form.errors["email"])

    def test_email_change_conflict_is_fail_closed_case_insensitively(self):
        token = make_email_change_token(self.user, "reserved@example.com")
        User.objects.create_user(
            username="reservation-winner",
            email="RESERVED@example.com",
            password=PASSWORD,
        )
        self.assertIsNone(apply_email_change_token(token))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "Credential.User@example.com")

    def test_successful_email_change_rotates_authenticated_session(self):
        self.client.force_login(self.user)
        old_session_key = self.client.session.session_key
        token = make_email_change_token(self.user, "rotated@example.com")
        response = self.client.post(
            reverse("accounts:email_change_confirm", args=[token])
        )
        self.assertRedirects(response, reverse("accounts:email_change_complete"))
        self.assertNotEqual(self.client.session.session_key, old_session_key)
        self.assertFalse(Session.objects.filter(session_key=old_session_key).exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    @override_settings(RATE_LIMIT_ENABLED=True)
    def test_password_change_current_password_attempts_are_limited(self):
        self.client.force_login(self.user)
        url = reverse("accounts:password_change")
        for _ in range(5):
            self.assertEqual(
                self.client.post(
                    url,
                    {
                        "old_password": "wrong-password",
                        "new_password1": "NewCredentialPassword2027!",
                        "new_password2": "NewCredentialPassword2027!",
                    },
                ).status_code,
                200,
            )
        blocked = self.client.post(
            url,
            {
                "old_password": "wrong-password",
                "new_password1": "NewCredentialPassword2027!",
                "new_password2": "NewCredentialPassword2027!",
            },
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    @override_settings(RATE_LIMIT_ENABLED=True)
    @patch("accounts.email_change_views.send_email_change_verification")
    def test_email_change_current_password_attempts_are_limited(
        self,
        send_verification,
    ):
        self.client.force_login(self.user)
        url = reverse("accounts:email_change")
        for index in range(5):
            self.assertEqual(
                self.client.post(
                    url,
                    {
                        "current_password": "wrong-password",
                        "new_email": f"attempt-{index}@example.com",
                    },
                ).status_code,
                200,
            )
        blocked = self.client.post(
            url,
            {
                "current_password": "wrong-password",
                "new_email": "blocked@example.com",
            },
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)
        send_verification.assert_not_called()

    def test_token_confirmation_pages_do_not_send_token_referrers(self):
        verification_user = User.objects.create_user(
            username="referrer-verification",
            email="referrer-verification@example.com",
            password=PASSWORD,
            user_type=User.UserType.USER,
            is_verified=False,
        )
        verification_token = make_email_verification_token(verification_user)
        verification_response = self.client.get(
            reverse("accounts:email_verification_confirm", args=[verification_token])
        )
        self.assertEqual(
            verification_response.headers["Referrer-Policy"],
            "no-referrer",
        )

        self.client.force_login(self.user)
        change_token = make_email_change_token(self.user, "referrer-new@example.com")
        change_response = self.client.get(
            reverse("accounts:email_change_confirm", args=[change_token])
        )
        self.assertEqual(change_response.headers["Referrer-Policy"], "no-referrer")


class PasswordResetSerializationTests(TestCase):
    def test_password_reset_rechecks_token_under_a_user_row_lock(self):
        user = User.objects.create_user(
            username="locked-reset-user",
            email="locked-reset-user@example.com",
            password=PASSWORD,
            user_type=User.UserType.USER,
            is_verified=True,
        )
        token = password_reset_token_generator.make_token(user)
        route = reverse(
            "accounts:password_reset_confirm",
            kwargs={
                "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
                "token": token,
            },
        )
        first = self.client.get(route)
        with patch.object(
            User.objects,
            "select_for_update",
            wraps=User.objects.select_for_update,
        ) as select_for_update:
            response = self.client.post(
                first["Location"],
                {
                    "new_password1": "SerializedReset2027!",
                    "new_password2": "SerializedReset2027!",
                },
            )
        self.assertRedirects(response, reverse("accounts:password_reset_complete"))
        select_for_update.assert_called_once_with()
        user.refresh_from_db()
        self.assertTrue(user.check_password("SerializedReset2027!"))
