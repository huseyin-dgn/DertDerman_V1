from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import Client, TestCase
from django.urls import reverse

from .forms import COMPANY_LOGIN_ERROR
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
            "password1": PASSWORD,
            "password2": PASSWORD,
            # Public POST verileri ayrıcalık yükseltememeli.
            "username": f"public-{suffix}",
            "user_type": User.UserType.ADMIN,
            "is_staff": "on",
            "is_superuser": "on",
            "approval_status": Company.ApprovalStatus.APPROVED,
            "is_verified": "on",
            "role": CompanyMembership.Role.MANAGER,
            "is_active": "on",
        }

    def register(self, suffix="one"):
        data = self.registration_data(suffix)
        response = self.client.post(reverse("company_auth:register"), data)
        user = User.objects.get(email=data["email"])
        membership = CompanyMembership.objects.select_related("company").get(user=user)
        return response, user, membership.company, membership

    def company_login(self, email, password=PASSWORD, query=""):
        return self.client.post(
            reverse("company_auth:login") + query,
            {"email": email, "password": password},
        )

    def assert_login_denied(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, COMPANY_LOGIN_ERROR)
        self.assertNotIn("_auth_user_id", self.client.session)

    def approve(self, company):
        self.client.force_login(self.admin)
        detail_url = reverse("adminx:company_application_detail", args=[company.pk])
        response = self.client.post(detail_url, {"action": "approve"})
        self.client.logout()
        return response, detail_url

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

    def test_public_company_auth_routes_render_email_fields_without_username(self):
        login = self.client.get(reverse("company_auth:login"))
        register = self.client.get(reverse("company_auth:register"))

        self.assertEqual(login.status_code, 200)
        self.assertEqual(register.status_code, 200)
        self.assertContains(login, 'name="email"')
        self.assertContains(login, 'autocomplete="email"')
        self.assertContains(login, 'autocomplete="current-password"')
        self.assertNotContains(login, 'name="username"')
        self.assertNotContains(register, 'name="username"')
        self.assertContains(register, 'autocomplete="email"')
        self.assertContains(register, 'autocomplete="new-password"', count=2)

    def test_valid_registration_creates_pending_unprivileged_records(self):
        response, user, company, membership = self.register("valid")

        self.assertRedirects(response, reverse("company_auth:login"))
        self.assertEqual(user.user_type, User.UserType.COMPANY)
        self.assertEqual(user.email, "company-valid@example.com")
        self.assertTrue(user.username.startswith("company_"))
        self.assertNotEqual(user.username, "public-valid")
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

    def test_registration_normalizes_email_and_rejects_case_insensitive_duplicate(self):
        data = self.registration_data("normalized")
        data["email"] = "  Company-Normalized@Example.COM  "
        response = self.client.post(reverse("company_auth:register"), data)
        self.assertRedirects(response, reverse("company_auth:login"))
        self.assertEqual(
            User.objects.get(email__iexact="company-normalized@example.com").email,
            "company-normalized@example.com",
        )

        duplicate = self.registration_data("duplicate")
        duplicate["email"] = "COMPANY-NORMALIZED@EXAMPLE.COM"
        response = self.client.post(reverse("company_auth:register"), duplicate)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bu e-posta adresiyle daha önce bir hesap oluşturulmuş.")
        self.assertEqual(User.objects.filter(email__iexact=duplicate["email"]).count(), 1)

    def test_pending_company_login_is_denied_with_generic_error(self):
        _, user, _, _ = self.register("pending")
        self.assert_login_denied(self.company_login(user.email))

    def test_approved_but_unverified_company_login_is_denied(self):
        _, user, company, membership = self.register("unverified")
        company.approval_status = Company.ApprovalStatus.APPROVED
        company.is_active = True
        company.save(update_fields=["approval_status", "is_active"])
        membership.is_active = True
        membership.save(update_fields=["is_active"])

        self.assert_login_denied(self.company_login(user.email))

    def test_admin_approval_activates_all_required_records_and_enables_login(self):
        _, user, company, membership = self.register("approved")
        user.is_active = False
        user.save(update_fields=["is_active"])

        response, detail_url = self.approve(company)

        self.assertRedirects(response, detail_url, fetch_redirect_response=False)
        company.refresh_from_db()
        membership.refresh_from_db()
        user.refresh_from_db()
        self.assertEqual(company.approval_status, Company.ApprovalStatus.APPROVED)
        self.assertTrue(company.is_active)
        self.assertTrue(company.is_verified)
        self.assertTrue(membership.is_active)
        self.assertTrue(user.is_active)

        response = self.company_login(
            f"  {user.email.upper()}  ",
            query="?next=https://example.com/escape",
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
        self.assertFalse(company.is_verified)
        self.assertFalse(membership.is_active)

        self.client.logout()
        self.assert_login_denied(self.company_login(user.email))

    def test_wrong_email_wrong_password_and_non_company_roles_use_generic_error(self):
        _, user, company, _ = self.register("credentials")
        self.approve(company)

        cases = (
            ("missing@example.com", PASSWORD),
            (user.email, "WrongPassword2026!"),
            (self.regular_user.email, PASSWORD),
            (self.admin.email, PASSWORD),
        )
        for email, password in cases:
            with self.subTest(email=email):
                self.assert_login_denied(self.company_login(email, password))

    def test_username_is_not_accepted_as_company_login_identifier(self):
        _, user, company, _ = self.register("username-denied")
        self.approve(company)

        response = self.client.post(
            reverse("company_auth:login"),
            {"username": user.username, "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_user_membership_or_company_cannot_login(self):
        for inactive_target in ("user", "membership", "company"):
            with self.subTest(inactive_target=inactive_target):
                _, user, company, membership = self.register(f"inactive-{inactive_target}")
                self.approve(company)
                target = {"user": user, "membership": membership, "company": company}[inactive_target]
                target.is_active = False
                target.save(update_fields=["is_active"])
                self.assert_login_denied(self.company_login(user.email))

    def test_authenticated_approved_company_is_redirected_from_auth_pages(self):
        _, user, company, _ = self.register("authenticated")
        self.approve(company)
        self.client.force_login(user)

        for url_name in ("company_auth:login", "company_auth:register"):
            with self.subTest(url_name=url_name):
                self.assertRedirects(
                    self.client.get(reverse(url_name)),
                    reverse("companies:company_panel"),
                )

    def test_application_management_is_admin_only_and_get_is_read_only(self):
        _, _, company, _ = self.register("permissions")
        list_url = reverse("adminx:company_application_list")
        detail_url = reverse("adminx:company_application_detail", args=[company.pk])
        company_user = User.objects.create_user(
            username="company-role-only",
            email="company-role-only@example.com",
            password=PASSWORD,
            user_type=User.UserType.COMPANY,
        )
        for user in (self.regular_user, company_user):
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
            client.post(
                reverse("company_auth:register"),
                self.registration_data("csrf-register"),
            ).status_code,
            403,
        )
        self.assertEqual(
            client.post(
                reverse("company_auth:login"),
                {"email": self.regular_user.email, "password": PASSWORD},
            ).status_code,
            403,
        )

    def test_approved_membership_does_not_allow_cross_company_access(self):
        _, user_a, company_a, membership_a = self.register("cross-a")
        _, _, company_b, membership_b = self.register("cross-b")
        for company, membership in ((company_a, membership_a), (company_b, membership_b)):
            company.approval_status = Company.ApprovalStatus.APPROVED
            company.is_active = True
            company.is_verified = True
            company.save(update_fields=["approval_status", "is_active", "is_verified"])
            membership.is_active = True
            membership.save(update_fields=["is_active"])

        self.client.force_login(user_a)
        own = reverse("companies:company_panel_detail", kwargs={"slug": company_a.slug})
        other = reverse("companies:company_panel_detail", kwargs={"slug": company_b.slug})
        self.assertEqual(self.client.get(own).status_code, 200)
        self.assertEqual(self.client.get(other).status_code, 403)
