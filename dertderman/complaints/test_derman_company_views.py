from datetime import timedelta

from django.contrib.auth import (
    get_user_model,
)
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import (
    Company,
    CompanyMembership,
    CompanySubscription,
)

from .models import (
    Complaint,
    DermanCompanyResponse,
    DermanPost,
)


User = get_user_model()


class DermanCompanyResponseViewTests(
    TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls.complaint_owner = (
            User.objects.create_user(
                username="dcv-owner-user",
                email=(
                    "dcv-owner-user@example.com"
                ),
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.derman_author = (
            User.objects.create_user(
                username="dcv-author",
                email="dcv-author@example.com",
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.company_owner = (
            User.objects.create_user(
                username="dcv-company-owner",
                email=(
                    "dcv-company-owner@example.com"
                ),
                user_type=(
                    User.UserType.COMPANY
                ),
            )
        )

        cls.company_manager = (
            User.objects.create_user(
                username="dcv-manager",
                email="dcv-manager@example.com",
                user_type=(
                    User.UserType.COMPANY
                ),
            )
        )

        cls.company_support = (
            User.objects.create_user(
                username="dcv-support",
                email="dcv-support@example.com",
                user_type=(
                    User.UserType.COMPANY
                ),
            )
        )

        cls.normal_user = (
            User.objects.create_user(
                username="dcv-normal-user",
                email=(
                    "dcv-normal-user@example.com"
                ),
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.company = (
            Company.objects.create(
                name="DCV Company",
                is_active=True,
                is_verified=True,
                approval_status=(
                    Company
                    .ApprovalStatus
                    .APPROVED
                ),
            )
        )

        CompanyMembership.objects.create(
            user=cls.company_owner,
            company=cls.company,
            role=(
                CompanyMembership.Role.OWNER
            ),
            is_active=True,
        )

        CompanyMembership.objects.create(
            user=cls.company_manager,
            company=cls.company,
            role=(
                CompanyMembership.Role.MANAGER
            ),
            is_active=True,
        )

        CompanyMembership.objects.create(
            user=cls.company_support,
            company=cls.company,
            role=(
                CompanyMembership.Role.SUPPORT
            ),
            is_active=True,
        )

        cls.subscription = (
            CompanySubscription.objects.create(
                company=cls.company,
                plan=(
                    CompanySubscription.Plan.PRO
                ),
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
        )

        cls.complaint = (
            Complaint.objects.create(
                user=cls.complaint_owner,
                company=cls.company,
                title=(
                    "Derman company view testi"
                ),
                description=(
                    "Derman company response "
                    "view testleri için yeterince "
                    "uzun açıklama."
                ),
                status=(
                    Complaint.Status.PUBLISHED
                ),
            )
        )

        cls.derman = (
            DermanPost.objects.create(
                complaint=cls.complaint,
                author_user=cls.derman_author,
                body=(
                    "View testleri için "
                    "yayınlanmış geçerli "
                    "Derman içeriği."
                ),
                status=(
                    DermanPost.Status.PUBLISHED
                ),
                published_at=timezone.now(),
            )
        )

    def create_url(self):
        return reverse(
            (
                "complaints:"
                "derman_company_response_create"
            ),
            kwargs={
                "derman_pk": self.derman.pk,
            },
        )

    def update_url(self):
        return reverse(
            (
                "complaints:"
                "derman_company_response_update"
            ),
            kwargs={
                "derman_pk": self.derman.pk,
            },
        )

    def test_owner_can_create_response(
        self,
    ):
        self.client.force_login(
            self.company_owner
        )

        response = self.client.post(
            self.create_url(),
            {
                "body": (
                    "Şirketin Derman hakkında "
                    "yayınladığı resmi yanıt."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            DermanCompanyResponse.objects
            .filter(
                derman=self.derman,
                company=self.company,
            )
            .exists()
        )

    def test_manager_can_create_response(
        self,
    ):
        self.client.force_login(
            self.company_manager
        )

        response = self.client.post(
            self.create_url(),
            {
                "body": (
                    "Manager tarafından "
                    "yayınlanan resmi şirket "
                    "Derman yanıtı."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertEqual(
            DermanCompanyResponse.objects
            .get(
                derman=self.derman,
            )
            .author_user_id,
            self.company_manager.pk,
        )

    def test_support_gets_403(
        self,
    ):
        self.client.force_login(
            self.company_support
        )

        response = self.client.post(
            self.create_url(),
            {
                "body": (
                    "Support tarafından "
                    "gönderilememesi gereken "
                    "bir şirket yanıtı."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertFalse(
            DermanCompanyResponse.objects
            .exists()
        )

    def test_user_gets_403(
        self,
    ):
        self.client.force_login(
            self.normal_user
        )

        response = self.client.post(
            self.create_url(),
            {
                "body": (
                    "Normal kullanıcı bu "
                    "yanıtı oluşturamamalıdır."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_get_is_not_allowed(
        self,
    ):
        self.client.force_login(
            self.company_owner
        )

        response = self.client.get(
            self.create_url()
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_short_body_does_not_create(
        self,
    ):
        self.client.force_login(
            self.company_owner
        )

        response = self.client.post(
            self.create_url(),
            {
                "body": "Kısa.",
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            DermanCompanyResponse.objects
            .exists()
        )

    def test_standard_company_cannot_create(
        self,
    ):
        self.subscription.is_active = False

        self.subscription.save(
            update_fields=(
                "is_active",
                "updated_at",
            )
        )

        self.client.force_login(
            self.company_owner
        )

        response = self.client.post(
            self.create_url(),
            {
                "body": (
                    "Standart şirket "
                    "hesabından gönderilmeye "
                    "çalışılan resmi yanıt."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            DermanCompanyResponse.objects
            .exists()
        )

    def test_owner_can_update_response(
        self,
    ):
        company_response = (
            DermanCompanyResponse.objects
            .create(
                derman=self.derman,
                company=self.company,
                author_user=(
                    self.company_owner
                ),
                body=(
                    "İlk şirket cevabı "
                    "yeterince uzun durumdadır."
                ),
            )
        )

        self.client.force_login(
            self.company_manager
        )

        response = self.client.post(
            self.update_url(),
            {
                "body": (
                    "Manager tarafından "
                    "güncellenmiş resmi "
                    "şirket cevabıdır."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        company_response.refresh_from_db()

        self.assertEqual(
            company_response.body,
            (
                "Manager tarafından "
                "güncellenmiş resmi "
                "şirket cevabıdır."
            ),
        )

        self.assertEqual(
            company_response.author_user_id,
            self.company_owner.pk,
        )

    def test_missing_response_is_not_created_by_update(
        self,
    ):
        self.client.force_login(
            self.company_owner
        )

        response = self.client.post(
            self.update_url(),
            {
                "body": (
                    "Olmayan cevap update "
                    "endpointinden "
                    "oluşturulmamalıdır."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            DermanCompanyResponse.objects
            .exists()
        )

    def test_resolved_complaint_blocks_create(
        self,
    ):
        self.complaint.status = (
            Complaint.Status.RESOLVED
        )

        self.complaint.save(
            update_fields=(
                "status",
                "updated_at",
            )
        )

        self.client.force_login(
            self.company_owner
        )

        response = self.client.post(
            self.create_url(),
            {
                "body": (
                    "Resolved şikayette "
                    "oluşturulmaması gereken "
                    "resmi şirket yanıtı."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            DermanCompanyResponse.objects
            .exists()
        )