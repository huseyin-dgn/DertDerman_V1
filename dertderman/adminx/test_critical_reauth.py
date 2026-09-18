from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.test import (
    Client,
    TestCase,
    override_settings,
)
from django.urls import reverse

from companies.models import (
    Company,
    CompanyMembership,
)


@override_settings(
    AUTH_SESSION_SECURITY_ENABLED=True,
)
class CriticalAdminReauthenticationTests(TestCase):
    password = "CriticalReauthPassword2026!"

    def setUp(self):
        User = get_user_model()

        self.admin = User.objects.create_user(
            username="critical-admin",
            email="critical-admin@example.com",
            password=self.password,
            user_type="ADMIN",
        )

        self.target = User.objects.create_user(
            username="critical-target",
            email="critical-target@example.com",
            password=self.password,
            user_type="USER",
            is_verified=True,
        )

    def test_stale_admin_session_cannot_permanently_close_user(self):
        client = Client()

        # force_login is deliberately used here:
        # this simulates an authenticated session without a
        # recent password-authentication timestamp.
        client.force_login(
            self.admin
        )

        response = client.post(
            reverse(
                "adminx:permanently_close_user",
                args=[self.target.pk],
            ),
            {
                "confirm_username":
                    self.target.username,
                "reason":
                    "This operation must be blocked.",
            },
        )

        safe_next = reverse(
            "adminx:user_detail",
            args=[self.target.pk],
        )

        expected = (
            reverse("adminx:reauth")
            + "?"
            + urlencode(
                {
                    "next": safe_next,
                }
            )
        )

        self.assertRedirects(
            response,
            expected,
            fetch_redirect_response=False,
        )

        self.target.refresh_from_db()

        self.assertFalse(
            self.target.is_permanently_closed
        )

        self.assertTrue(
            self.target.is_active
        )

    def _stale_admin_client(self):
        client = Client()
        client.force_login(
            self.admin
        )
        return client

    def _assert_reauth_redirect(
        self,
        response,
        *,
        safe_next,
    ):
        expected = (
            reverse("adminx:reauth")
            + "?"
            + urlencode(
                {
                    "next": safe_next,
                }
            )
        )

        self.assertRedirects(
            response,
            expected,
            fetch_redirect_response=False,
        )

    def test_stale_admin_session_cannot_archive_company(self):
        company = Company.objects.create(
            name="Critical Reauth Company",
        )

        client = self._stale_admin_client()

        response = client.post(
            reverse(
                "adminx:company_archive",
                args=[company.pk],
            )
        )

        self._assert_reauth_redirect(
            response,
            safe_next=reverse(
                "adminx:company_edit",
                args=[company.pk],
            ),
        )

        company.refresh_from_db()

        self.assertIsNone(
            company.archived_at
        )

    def test_stale_admin_session_cannot_suspend_user(self):
        client = self._stale_admin_client()

        response = client.post(
            reverse(
                "adminx:user_suspend",
                args=[self.target.pk],
            ),
            {
                "reason":
                    "Blocked until reauthentication.",
            },
        )

        self._assert_reauth_redirect(
            response,
            safe_next=reverse(
                "adminx:user_detail",
                args=[self.target.pk],
            ),
        )

        self.target.refresh_from_db()

        self.assertFalse(
            self.target.is_suspended
        )

    def test_stale_admin_session_cannot_unsuspend_user(self):
        get_user_model().objects.filter(
            pk=self.target.pk
        ).update(
            is_suspended=True,
        )

        client = self._stale_admin_client()

        response = client.post(
            reverse(
                "adminx:user_unsuspend",
                args=[self.target.pk],
            )
        )

        self._assert_reauth_redirect(
            response,
            safe_next=reverse(
                "adminx:user_detail",
                args=[self.target.pk],
            ),
        )

        self.target.refresh_from_db()

        self.assertTrue(
            self.target.is_suspended
        )

    def _pending_company_application(
        self,
        *,
        suffix,
    ):
        User = get_user_model()

        owner = User.objects.create_user(
            username=f"application-owner-{suffix}",
            email=f"application-owner-{suffix}@example.com",
            password=self.password,
            user_type="COMPANY",
        )

        company = Company.objects.create(
            name=f"Critical Application {suffix}",
            email=owner.email,
            approval_status=(
                Company.ApprovalStatus.PENDING
            ),
            is_active=False,
            is_verified=False,
        )

        membership = (
            CompanyMembership.objects.create(
                company=company,
                user=owner,
                role=(
                    CompanyMembership.Role.OWNER
                ),
                is_active=False,
            )
        )

        return company, membership

    def test_stale_admin_cannot_approve_company_application(self):
        company, membership = (
            self._pending_company_application(
                suffix="approve",
            )
        )

        client = self._stale_admin_client()

        response = client.post(
            reverse(
                "adminx:company_application_detail",
                args=[company.pk],
            ),
            {
                "action": "approve",
                "rejection_reason": "",
            },
        )

        self._assert_reauth_redirect(
            response,
            safe_next=reverse(
                "adminx:company_application_detail",
                args=[company.pk],
            ),
        )

        company.refresh_from_db()
        membership.refresh_from_db()

        self.assertEqual(
            company.approval_status,
            Company.ApprovalStatus.PENDING,
        )
        self.assertFalse(
            company.is_active
        )
        self.assertFalse(
            company.is_verified
        )
        self.assertFalse(
            membership.is_active
        )

    def test_stale_admin_cannot_reject_company_application(self):
        company, membership = (
            self._pending_company_application(
                suffix="reject",
            )
        )

        client = self._stale_admin_client()

        response = client.post(
            reverse(
                "adminx:company_application_detail",
                args=[company.pk],
            ),
            {
                "action": "reject",
                "rejection_reason":
                    "This decision requires fresh authentication.",
            },
        )

        self._assert_reauth_redirect(
            response,
            safe_next=reverse(
                "adminx:company_application_detail",
                args=[company.pk],
            ),
        )

        company.refresh_from_db()
        membership.refresh_from_db()

        self.assertEqual(
            company.approval_status,
            Company.ApprovalStatus.PENDING,
        )
        self.assertEqual(
            company.rejection_reason,
            "",
        )
        self.assertIsNone(
            company.rejected_at
        )
        self.assertFalse(
            membership.is_active
        )

    def test_real_admin_login_has_recent_authentication(self):
        client = Client()

        login_response = client.post(
            reverse("adminx:login"),
            {
                "username":
                    self.admin.username,
                "password":
                    self.password,
            },
        )

        self.assertRedirects(
            login_response,
            reverse("adminx:home"),
        )

        response = client.get(
            reverse("adminx:reauth")
        )

        self.assertEqual(
            response.status_code,
            200,
        )
