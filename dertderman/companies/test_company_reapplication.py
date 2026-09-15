from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import (
    Company,
    CompanyCategory,
    CompanyMembership,
)
from companies.services import (
    decide_company_application,
)


User = get_user_model()


class CompanyReapplicationTests(TestCase):

    def setUp(self):
        self.password = "StrongPass2026!"

        self.admin = User.objects.create_user(
            username="reapplication-admin",
            email="reapplication-admin@example.com",
            user_type=User.UserType.ADMIN,
        )

        self.user = User.objects.create_user(
            username="rejected-company-owner",
            email="rejected@example.com",
            password=self.password,
            user_type=User.UserType.COMPANY,
            is_verified=False,
            phone="05000000000",
        )

        self.category = (
            CompanyCategory.objects.create(
                name="Old Category",
            )
        )

        self.new_category = (
            CompanyCategory.objects.create(
                name="New Category",
            )
        )

        self.company = Company.objects.create(
            name="Rejected Company",
            email=self.user.email,
            phone=self.user.phone,
            category=self.category,
            approval_status=(
                Company.ApprovalStatus.REJECTED
            ),
            is_active=False,
            is_verified=False,
        )

        self.membership = (
            CompanyMembership.objects.create(
                user=self.user,
                company=self.company,
                role=CompanyMembership.Role.OWNER,
                is_active=False,
            )
        )

        self.url = reverse(
            "company_auth:reapply"
        )

    def valid_data(self):
        return {
            "company_name":
                "Corrected Company",

            "category":
                str(self.new_category.pk),

            "email":
                self.user.email,

            "phone":
                "05551112233",

            "website":
                "https://example.com",

            "password":
                self.password,
        }

    def test_reapplication_page_is_available(self):
        response = self.client.get(
            self.url
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            "Yeniden İncelemeye Gönder",
        )

    def test_wrong_password_does_not_reopen_application(self):
        data = self.valid_data()

        data["password"] = (
            "WrongPassword2026!"
        )

        response = self.client.post(
            self.url,
            data,
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            (
                "Yeniden başvuru bilgileri "
                "doğrulanamadı."
            ),
        )

        self.company.refresh_from_db()

        self.assertEqual(
            self.company.approval_status,
            Company.ApprovalStatus.REJECTED,
        )

    def test_rejected_application_can_be_resubmitted(self):
        user_count = User.objects.count()
        company_count = Company.objects.count()
        membership_count = (
            CompanyMembership.objects.count()
        )

        response = self.client.post(
            self.url,
            self.valid_data(),
        )

        self.assertRedirects(
            response,
            reverse(
                "company_auth:login"
            ),
        )

        self.company.refresh_from_db()
        self.membership.refresh_from_db()
        self.user.refresh_from_db()

        self.assertEqual(
            self.company.approval_status,
            Company.ApprovalStatus.PENDING,
        )

        self.assertFalse(
            self.company.is_active
        )

        self.assertFalse(
            self.company.is_verified
        )

        self.assertFalse(
            self.membership.is_active
        )

        self.assertEqual(
            self.company.name,
            "Corrected Company",
        )

        self.assertEqual(
            self.company.category,
            self.new_category,
        )

        self.assertEqual(
            self.company.phone,
            "05551112233",
        )

        self.assertEqual(
            self.user.phone,
            "05551112233",
        )

        # Yeni hesap/kayit uretilmemeli.
        self.assertEqual(
            User.objects.count(),
            user_count,
        )

        self.assertEqual(
            Company.objects.count(),
            company_count,
        )

        self.assertEqual(
            CompanyMembership.objects.count(),
            membership_count,
        )

    def test_pending_application_still_cannot_login(self):
        self.client.post(
            self.url,
            self.valid_data(),
        )

        response = self.client.post(
            reverse(
                "company_auth:login"
            ),
            {
                "email":
                    self.user.email,

                "password":
                    self.password,
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            (
                "Kurumsal giriş bilgileri "
                "doğrulanamadı."
            ),
        )

    def test_approved_company_cannot_use_reapplication(self):
        Company.objects.filter(
            pk=self.company.pk
        ).update(
            approval_status=(
                Company.ApprovalStatus.APPROVED
            ),
            is_active=True,
            is_verified=True,
        )

        self.membership.is_active = True

        self.membership.save(
            update_fields=[
                "is_active"
            ]
        )

        response = self.client.post(
            self.url,
            self.valid_data(),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            (
                "Yeniden başvuru bilgileri "
                "doğrulanamadı."
            ),
        )

        self.company.refresh_from_db()

        self.assertEqual(
            self.company.approval_status,
            Company.ApprovalStatus.APPROVED,
        )

    def test_archived_rejected_company_cannot_reapply(self):
        Company.objects.filter(
            pk=self.company.pk
        ).update(
            archived_at=timezone.now(),
        )

        response = self.client.post(
            self.url,
            self.valid_data(),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.company.refresh_from_db()

        self.assertEqual(
            self.company.approval_status,
            Company.ApprovalStatus.REJECTED,
        )

    def test_admin_can_approve_resubmitted_application(self):
        response = self.client.post(
            self.url,
            self.valid_data(),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.company.refresh_from_db()

        company, changed = (
            decide_company_application(
                self.company.pk,
                Company.ApprovalStatus.APPROVED,
                actor=self.admin,
            )
        )

        self.assertTrue(
            changed
        )

        self.membership.refresh_from_db()

        self.assertTrue(
            company.is_active
        )

        self.assertTrue(
            company.is_verified
        )

        self.assertTrue(
            self.membership.is_active
        )

        login_response = self.client.post(
            reverse(
                "company_auth:login"
            ),
            {
                "email":
                    self.user.email,

                "password":
                    self.password,
            },
        )

        self.assertEqual(
            login_response.status_code,
            302,
        )
