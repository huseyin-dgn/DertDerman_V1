

from django.contrib.auth import (
    get_user_model,
)
from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import (
    Company,
    CompanyMembership,
    CompanySubscription,
)

from .derman_selectors import (
    DermanAccessLevel,
)
from .forms import (
    DermanCompanyResponseForm,
)
from .models import (
    Complaint,
    DermanCompanyResponse,
    DermanPost,
)


User = get_user_model()


class DermanCompanyContextTests(
    TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls.complaint_owner = (
            User.objects.create_user(
                username=(
                    "dcc-complaint-owner"
                ),
                email=(
                    "dcc-complaint-owner"
                    "@example.com"
                ),
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.derman_author = (
            User.objects.create_user(
                username="dcc-author",
                email="dcc-author@example.com",
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.user_viewer = (
            User.objects.create_user(
                username="dcc-viewer",
                email="dcc-viewer@example.com",
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.company_manager = (
            User.objects.create_user(
                username="dcc-manager",
                email="dcc-manager@example.com",
                user_type=(
                    User.UserType.COMPANY
                ),
            )
        )

        cls.company_support = (
            User.objects.create_user(
                username="dcc-support",
                email="dcc-support@example.com",
                user_type=(
                    User.UserType.COMPANY
                ),
            )
        )

        cls.company_owner = (
            User.objects.create_user(
                username="dcc-company-owner",
                email=(
                    "dcc-company-owner"
                    "@example.com"
                ),
                user_type=(
                    User.UserType.COMPANY
                ),
            )
        )

        cls.company = (
            Company.objects.create(
                name="DCC Company",
                is_active=True,
                is_verified=True,
                approval_status=(
                    Company
                    .ApprovalStatus
                    .APPROVED
                ),
            )
        )

        cls.complaint = (
            Complaint.objects.create(
                user=cls.complaint_owner,
                company=cls.company,
                title=(
                    "Derman şirket context "
                    "testi"
                ),
                description=(
                    "Derman şirket context "
                    "testleri için yeterince "
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
                author_user=(
                    cls.derman_author
                ),
                body=(
                    "Şirket cevabı context "
                    "testleri için yayınlanmış "
                    "Derman içeriği."
                ),
                status=(
                    DermanPost.Status.PUBLISHED
                ),
                published_at=timezone.now(),
            )
        )

        cls.company_response = (
            DermanCompanyResponse.objects
            .create(
                derman=cls.derman,
                company=cls.company,
                author_user=(
                    cls.company_owner
                ),
                body=(
                    "Şirketin bu Derman için "
                    "yayınladığı resmi cevap "
                    "içeriğidir."
                ),
            )
        )

        cls.url = reverse(
            "complaints:public_detail",
            args=[
                cls.complaint.pk
            ],
        )

    def _create_pro(
        self,
    ):
        return (
            CompanySubscription.objects
            .create(
                company=self.company,
                plan=(
                    CompanySubscription
                    .Plan
                    .PRO
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

    def test_user_sees_official_company_response(
        self,
    ):
        self.client.force_login(
            self.user_viewer
        )

        response = self.client.get(
            self.url
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        visibility = (
            response.context[
                "derman_visibility"
            ]
        )

        dermans = list(
            visibility.dermans
        )

        self.assertEqual(
            len(dermans),
            1,
        )

        self.assertEqual(
            dermans[0][
                "company_response_id"
            ],
            self.company_response.pk,
        )

        self.assertEqual(
            dermans[0][
                "company_response_body"
            ],
            self.company_response.body,
        )

        self.assertFalse(
            visibility.can_company_respond
        )

        self.assertIsNone(
            response.context[
                "derman_company_response_form"
            ]
        )

    def test_pro_manager_can_respond(
        self,
    ):
        CompanyMembership.objects.create(
            user=self.company_manager,
            company=self.company,
            role=(
                CompanyMembership
                .Role
                .MANAGER
            ),
            is_active=True,
        )

        self._create_pro()

        self.client.force_login(
            self.company_manager
        )

        response = self.client.get(
            self.url
        )

        visibility = (
            response.context[
                "derman_visibility"
            ]
        )

        self.assertEqual(
            visibility.access_level,
            DermanAccessLevel.COMPANY_PRO,
        )

        self.assertTrue(
            visibility.can_view_content
        )

        self.assertTrue(
            visibility.can_company_respond
        )

        self.assertIsInstance(
            response.context[
                "derman_company_response_form"
            ],
            DermanCompanyResponseForm,
        )

        dermans = list(
            visibility.dermans
        )

        self.assertEqual(
            dermans[0][
                "company_response_body"
            ],
            self.company_response.body,
        )

    def test_pro_support_can_view_but_cannot_respond(
        self,
    ):
        CompanyMembership.objects.create(
            user=self.company_support,
            company=self.company,
            role=(
                CompanyMembership
                .Role
                .SUPPORT
            ),
            is_active=True,
        )

        self._create_pro()

        self.client.force_login(
            self.company_support
        )

        response = self.client.get(
            self.url
        )

        visibility = (
            response.context[
                "derman_visibility"
            ]
        )

        self.assertEqual(
            visibility.access_level,
            DermanAccessLevel.COMPANY_PRO,
        )

        self.assertTrue(
            visibility.can_view_content
        )

        self.assertFalse(
            visibility.can_company_respond
        )

        self.assertIsNone(
            response.context[
                "derman_company_response_form"
            ]
        )

        dermans = list(
            visibility.dermans
        )

        self.assertEqual(
            dermans[0][
                "company_response_body"
            ],
            self.company_response.body,
        )

    def test_standard_company_gets_no_response_content(
        self,
    ):
        CompanyMembership.objects.create(
            user=self.company_owner,
            company=self.company,
            role=(
                CompanyMembership
                .Role
                .OWNER
            ),
            is_active=True,
        )

        self.client.force_login(
            self.company_owner
        )

        response = self.client.get(
            self.url
        )

        visibility = (
            response.context[
                "derman_visibility"
            ]
        )

        self.assertEqual(
            visibility.access_level,
            (
                DermanAccessLevel
                .COMPANY_STANDARD
            ),
        )

        self.assertFalse(
            visibility.can_view_content
        )

        self.assertFalse(
            visibility.can_company_respond
        )

        self.assertEqual(
            list(
                visibility.dermans
            ),
            [],
        )

        self.assertIsNone(
            response.context[
                "derman_company_response_form"
            ]
        )

    def test_resolved_complaint_keeps_response_visible_but_disables_company_mutation(
        self,
    ):
        CompanyMembership.objects.create(
            user=self.company_manager,
            company=self.company,
            role=(
                CompanyMembership
                .Role
                .MANAGER
            ),
            is_active=True,
        )

        self._create_pro()

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
            self.company_manager
        )

        response = self.client.get(
            self.url
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        visibility = (
            response.context[
                "derman_visibility"
            ]
        )

        self.assertTrue(
            visibility.can_view_content
        )

        self.assertFalse(
            visibility.can_company_respond
        )

        dermans = list(
            visibility.dermans
        )

        self.assertEqual(
            len(dermans),
            1,
        )

        self.assertEqual(
            dermans[0][
                "company_response_body"
            ],
            self.company_response.body,
        )

        self.assertIsNone(
            response.context[
                "derman_company_response_form"
            ]
        )
