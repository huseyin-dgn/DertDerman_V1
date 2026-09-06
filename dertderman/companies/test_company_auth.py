from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import Client, TestCase
from django.urls import reverse

from .models import Company, CompanyMembership


User = get_user_model()
PASSWORD = "StrongCompanyPass2026!"


class CompanyAuthenticationFlowTests(TestCase):
    def registration_data(self, suffix="one"):
        return {
            "company_name": f"Kurumsal {suffix}",
            "first_name": "Yetkili",
            "last_name": "Kişi",
            "email": f"company-{suffix}@example.com",
            "phone": "05551234567",
            "website": "https://example.com",
            "username": f"company-{suffix}",
            "password1": PASSWORD,
            "password2": PASSWORD,
            "user_type": User.UserType.ADMIN,
            "is_staff": "on",
            "is_superuser": "on",
            "approval_status": Company.ApprovalStatus.APPROVED,
            "is_verified": "on",
            "role": CompanyMembership.Role.MANAGER,
            "is_active": "on",
        }

    def register(self, suffix="one"):
        response = self.client.post(
            reverse("company_auth:register"),
            self.registration_data(suffix),
        )
        user = User.objects.get(username=f"company-{suffix}")
        membership = CompanyMembership.objects.select_related("company").get(user=user)
        return response, user, membership.company, membership

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="approval-admin",
            email="approval-admin@example.com",
            password=PASSWORD,
            user_type=User.UserType.ADMIN,
        )
        cls.regular_user = User.objects.create_user(
            username="regular-login-user",
            email="regular-login-user@example.com",
            password=PASSWORD,
            user_type=User.UserType.USER,
        )

    def test_public_company_auth_routes_render(self):
        self.assertEqual(self.client.get(reverse("company_auth:login")).status_code, 200)
        self.assertEqual(self.client.get(reverse("company_auth:register")).status_code, 200)

    def test_valid_registration_creates_pending_unprivileged_records(self):
        response, user, company, membership = self.register("valid")

        self.assertRedirects(response, reverse("company_auth:login"))
        self.assertEqual(user.user_type, User.UserType.COMPANY)
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_verified)
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(company.approval_status, Company.ApprovalStatus.PENDING)
        self.assertFalse(company.is_active)
        self.assertFalse(company.is_verified)
        self.assertEqual(membership.role, CompanyMembership.Role.OWNER)
        self.assertFalse(membership.is_active)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertIn(
            "Şirket başvurunuz alındı. Yönetim onayından sonra kurumsal hesabınız aktif olacaktır.",
            [str(message) for message in get_messages(response.wsgi_request)],
        )

    def test_pending_company_login_is_denied(self):
        _, user, _, _ = self.register("pending")
        response = self.client.post(
            reverse("company_auth:login"),
            {"username": user.username, "password": PASSWORD},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Şirket hesabınız henüz onaylanmadı.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_approval_activates_owner_and_enables_login(self):
        _, user, company, membership = self.register("approved")
        self.client.force_login(self.admin)
        detail_url = reverse("adminx:company_application_detail", args=[company.pk])

        response = self.client.post(detail_url, {"action": "approve"})

        self.assertRedirects(response, detail_url)
        company.refresh_from_db()
        membership.refresh_from_db()
        self.assertEqual(company.approval_status, Company.ApprovalStatus.APPROVED)
        self.assertTrue(company.is_active)
        self.assertFalse(company.is_verified)
        self.assertTrue(membership.is_active)

        self.client.logout()
        response = self.client.post(
            reverse("company_auth:login") + "?next=https://example.com/escape",
            {"username": user.username, "password": PASSWORD},
        )
        self.assertRedirects(response, reverse("companies:company_panel"))
        self.assertEqual(self.client.get(reverse("companies:company_panel")).status_code, 200)

    def test_rejected_company_login_is_denied(self):
        _, user, company, membership = self.register("rejected")
        self.client.force_login(self.admin)
        self.client.post(
            reverse("adminx:company_application_detail", args=[company.pk]),
            {"action": "reject"},
        )
        company.refresh_from_db()
        membership.refresh_from_db()
        self.assertEqual(company.approval_status, Company.ApprovalStatus.REJECTED)
        self.assertFalse(company.is_active)
        self.assertFalse(membership.is_active)

        self.client.logout()
        response = self.client.post(
            reverse("company_auth:login"),
            {"username": user.username, "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Şirket hesabınız kurumsal erişime uygun değil.")

    def test_user_and_admin_credentials_are_denied(self):
        for user in (self.regular_user, self.admin):
            with self.subTest(role=user.user_type):
                response = self.client.post(
                    reverse("company_auth:login"),
                    {"username": user.username, "password": PASSWORD},
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Kurumsal giriş bilgileri doğrulanamadı.")
                self.assertNotIn("_auth_user_id", self.client.session)

    def test_application_management_is_admin_only_and_get_is_read_only(self):
        _, _, company, _ = self.register("permissions")
        list_url = reverse("adminx:company_application_list")
        detail_url = reverse("adminx:company_application_detail", args=[company.pk])
        for user in (self.regular_user, User.objects.create_user(
            username="company-role-only",
            email="company-role-only@example.com",
            password=PASSWORD,
            user_type=User.UserType.COMPANY,
        )):
            client = Client()
            client.force_login(user)
            self.assertEqual(client.get(list_url).status_code, 403)
            self.assertEqual(client.get(detail_url).status_code, 403)
            self.assertEqual(client.post(detail_url, {"action": "approve"}).status_code, 403)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(list_url).status_code, 200)
        self.assertEqual(self.client.get(detail_url + "?action=approve").status_code, 200)
        company.refresh_from_db()
        self.assertEqual(company.approval_status, Company.ApprovalStatus.PENDING)

    def test_approval_requires_csrf_and_post(self):
        _, _, company, _ = self.register("csrf")
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        detail_url = reverse("adminx:company_application_detail", args=[company.pk])

        self.assertEqual(client.post(detail_url, {"action": "approve"}).status_code, 403)
        company.refresh_from_db()
        self.assertEqual(company.approval_status, Company.ApprovalStatus.PENDING)
        self.assertEqual(client.get(detail_url).status_code, 200)
        company.refresh_from_db()
        self.assertEqual(company.approval_status, Company.ApprovalStatus.PENDING)

    def test_company_registration_and_login_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(
            client.post(reverse("company_auth:register"), self.registration_data("csrf-register")).status_code,
            403,
        )
        self.assertEqual(
            client.post(
                reverse("company_auth:login"),
                {"username": self.regular_user.username, "password": PASSWORD},
            ).status_code,
            403,
        )

    def test_approved_membership_does_not_allow_cross_company_access(self):
        _, user_a, company_a, membership_a = self.register("cross-a")
        _, _, company_b, membership_b = self.register("cross-b")
        for company, membership in ((company_a, membership_a), (company_b, membership_b)):
            company.approval_status = Company.ApprovalStatus.APPROVED
            company.is_active = True
            company.save(update_fields=["approval_status", "is_active"])
            membership.is_active = True
            membership.save(update_fields=["is_active"])

        self.client.force_login(user_a)
        own = reverse("companies:company_panel_detail", kwargs={"slug": company_a.slug})
        other = reverse("companies:company_panel_detail", kwargs={"slug": company_b.slug})
        self.assertEqual(self.client.get(own).status_code, 200)
        self.assertEqual(self.client.get(other).status_code, 403)
