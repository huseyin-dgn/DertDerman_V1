from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from complaints.models import Complaint

from companies.models import (
    Company,
    CompanyCategory,
    CompanyMembership,
    CompanyResponse,
    CompanySubscription,
    InternalCompanyNote,
)


User = get_user_model()


class CompanyPlanPermissionTests(TestCase):

    def setUp(self):
        self.company_user = User.objects.create_user(
            username="company-plan-owner",
            email="company-plan-owner@example.com",
            password="StrongPass2026!",
            user_type=User.UserType.COMPANY,
            is_verified=True,
        )

        self.consumer = User.objects.create_user(
            username="company-plan-consumer",
            email="company-plan-consumer@example.com",
            password="StrongPass2026!",
            user_type=User.UserType.USER,
            is_verified=True,
        )

        category = CompanyCategory.objects.create(
            name="Plan Test Category",
        )

        self.company = Company.objects.create(
            name="Plan Test Company",
            description=(
                "Plan test public company description."
            ),
            category=category,
            is_active=True,
            is_verified=True,
            approval_status=(
                Company.ApprovalStatus.APPROVED
            ),
        )

        CompanyMembership.objects.create(
            user=self.company_user,
            company=self.company,
            role=CompanyMembership.Role.OWNER,
            is_active=True,
        )

        self.complaint = Complaint.objects.create(
            user=self.consumer,
            company=self.company,
            title="Test sikayet basligi",
            description=(
                "Bu aciklama test icin gereken minimum "
                "karakter uzunlugundan daha uzundur."
            ),
            status=Complaint.Status.PUBLISHED,
        )

        self.client.force_login(
            self.company_user
        )

    def activate_pro(self):
        return CompanySubscription.objects.create(
            company=self.company,
            plan=CompanySubscription.Plan.PRO,
            billing_period=(
                CompanySubscription
                .BillingPeriod
                .MONTHLY
            ),
            is_active=True,
            current_period_end=(
                timezone.now()
                + timedelta(days=30)
            ),
        )

    def expire(self, subscription):
        subscription.current_period_end = (
            timezone.now()
            - timedelta(seconds=1)
        )

        subscription.save(
            update_fields=(
                "current_period_end",
                "updated_at",
            )
        )

    def test_standard_company_sees_response_pro_lock(self):
        response = self.client.get(
            reverse(
                "companies:complaint_detail",
                kwargs={
                    "pk": self.complaint.pk
                },
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            "DERTDERMAN PRO",
        )

        self.assertContains(
            response,
            "Pro'ya Y\u00fckselt",
        )

        self.assertNotContains(
            response,
            reverse(
                "companies:response_create",
                kwargs={
                    "pk": self.complaint.pk
                },
            ),
        )

    def test_standard_company_cannot_post_response(self):
        response = self.client.post(
            reverse(
                "companies:response_create",
                kwargs={
                    "pk": self.complaint.pk
                },
            ),
            {
                "body": (
                    "Manual POST ile gonderilmeye "
                    "calisilan sirket cevabi."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertFalse(
            CompanyResponse.objects.filter(
                company=self.company,
                complaint=self.complaint,
            ).exists()
        )

    def test_pro_company_can_post_response(self):
        self.activate_pro()

        response = self.client.post(
            reverse(
                "companies:response_create",
                kwargs={
                    "pk": self.complaint.pk
                },
            ),
            {
                "body": (
                    "Sorununuzu inceliyoruz ve "
                    "cozum icin size donus yapacagiz."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            CompanyResponse.objects.filter(
                company=self.company,
                complaint=self.complaint,
            ).exists()
        )

    def test_standard_company_sees_internal_note_lock(self):
        response = self.client.get(
            reverse(
                "companies:complaint_detail",
                kwargs={
                    "pk": self.complaint.pk
                },
            )
        )

        self.assertContains(
            response,
            (
                "Dahili notlar da Pro "
                "paketine dahildir."
            ),
        )

        self.assertNotContains(
            response,
            reverse(
                "companies:note_create",
                kwargs={
                    "pk": self.complaint.pk
                },
            ),
        )

    def test_standard_company_cannot_post_internal_note(self):
        response = self.client.post(
            reverse(
                "companies:note_create",
                kwargs={
                    "pk": self.complaint.pk
                },
            ),
            {
                "body": (
                    "Standart firmanin "
                    "gonderememesi gereken not."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertFalse(
            InternalCompanyNote.objects.filter(
                company=self.company,
                complaint=self.complaint,
            ).exists()
        )

    def test_pro_company_can_post_internal_note(self):
        self.activate_pro()

        response = self.client.post(
            reverse(
                "companies:note_create",
                kwargs={
                    "pk": self.complaint.pk
                },
            ),
            {
                "body": (
                    "Yalnizca sirket ekibi "
                    "icin dahili takip notu."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            InternalCompanyNote.objects.filter(
                company=self.company,
                complaint=self.complaint,
            ).exists()
        )

    def test_public_profile_marks_standard_company(self):
        self.client.logout()

        response = self.client.get(
            reverse(
                "companies_public:company_detail",
                kwargs={
                    "slug": self.company.slug
                },
            )
        )

        self.assertContains(
            response,
            "Standart Firma",
        )

    def test_public_profile_marks_pro_company(self):
        self.activate_pro()
        self.client.logout()

        response = self.client.get(
            reverse(
                "companies_public:company_detail",
                kwargs={
                    "slug": self.company.slug
                },
            )
        )

        self.assertContains(
            response,
            "DertDerman Pro",
        )

    def test_directory_marks_standard_company(self):
        self.client.logout()

        response = self.client.get(
            reverse(
                "companies_public:company_list"
            )
        )

        self.assertContains(
            response,
            self.company.name,
        )

        self.assertContains(
            response,
            "Standart Firma",
        )

    def test_directory_marks_pro_company(self):
        self.activate_pro()
        self.client.logout()

        response = self.client.get(
            reverse(
                "companies_public:company_list"
            )
        )

        self.assertContains(
            response,
            "DertDerman Pro",
        )

    def test_expired_pro_is_standard_again(self):
        subscription = self.activate_pro()
        self.expire(subscription)

        response = self.client.get(
            reverse(
                "companies:complaint_detail",
                kwargs={
                    "pk": self.complaint.pk
                },
            )
        )

        self.assertContains(
            response,
            "Pro'ya Y\u00fckselt",
        )

    def test_old_response_remains_after_pro_expires(self):
        subscription = self.activate_pro()

        create_response = self.client.post(
            reverse(
                "companies:response_create",
                kwargs={
                    "pk": self.complaint.pk
                },
            ),
            {
                "body": (
                    "Bu cevap aktif Pro "
                    "doneminde yayinlandi."
                ),
            },
        )

        self.assertEqual(
            create_response.status_code,
            302,
        )

        self.expire(subscription)

        response_page = self.client.get(
            reverse(
                "companies:responses"
            )
        )

        self.assertContains(
            response_page,
            "Bu cevap aktif Pro",
        )

    def test_old_internal_note_remains_after_pro_expires(self):
        subscription = self.activate_pro()

        create_note = self.client.post(
            reverse(
                "companies:note_create",
                kwargs={
                    "pk": self.complaint.pk
                },
            ),
            {
                "body": (
                    "Bu eski dahili not "
                    "silinmemelidir."
                ),
            },
        )

        self.assertEqual(
            create_note.status_code,
            302,
        )

        self.expire(subscription)

        detail = self.client.get(
            reverse(
                "companies:complaint_detail",
                kwargs={
                    "pk": self.complaint.pk
                },
            )
        )

        self.assertContains(
            detail,
            "Bu eski dahili not",
        )

        self.assertContains(
            detail,
            "Salt okunur",
        )
