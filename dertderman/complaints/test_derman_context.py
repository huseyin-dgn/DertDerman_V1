from datetime import timedelta

from django.contrib.auth import get_user_model
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
from .forms import DermanCreateForm
from .models import (
    Complaint,
    DermanPost,
)


User = get_user_model()


class DermanPublicDetailContextTests(
    TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls.owner = (
            User.objects.create_user(
                username=(
                    "context-owner"
                ),
                email=(
                    "context-owner"
                    "@example.com"
                ),
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.viewer = (
            User.objects.create_user(
                username=(
                    "context-viewer"
                ),
                email=(
                    "context-viewer"
                    "@example.com"
                ),
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.derman_author = (
            User.objects.create_user(
                username=(
                    "context-derman-author"
                ),
                email=(
                    "context-derman-author"
                    "@example.com"
                ),
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.company_user = (
            User.objects.create_user(
                username=(
                    "context-company-user"
                ),
                email=(
                    "context-company-user"
                    "@example.com"
                ),
                user_type=(
                    User.UserType.COMPANY
                ),
            )
        )

        cls.company = (
            Company.objects.create(
                name=(
                    "Context Test Company"
                ),
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
                user=cls.owner,
                company=cls.company,
                title=(
                    "Derman context testi"
                ),
                description=(
                    "Derman public detail "
                    "context testi için "
                    "yeterince uzun açıklama."
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
                    "Bu Derman içeriği "
                    "public detail context "
                    "testi için yeterince "
                    "uzun bir metindir."
                ),
                status=(
                    DermanPost.Status.PUBLISHED
                ),
                published_at=(
                    timezone.now()
                ),
            )
        )

        cls.url = reverse(
            "complaints:public_detail",
            args=[cls.complaint.pk],
        )

    def test_anonymous_gets_count_but_not_body(
        self,
    ):
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

        self.assertEqual(
            visibility.access_level,
            DermanAccessLevel.ANONYMOUS,
        )

        self.assertEqual(
            visibility.published_count,
            1,
        )

        self.assertFalse(
            visibility.can_view_content
        )

        self.assertEqual(
            list(
                visibility.dermans
            ),
            [],
        )

        self.assertIsNone(
            response.context[
                "derman_create_form"
            ]
        )

    def test_user_gets_published_body_and_create_form(
        self,
    ):
        self.client.force_login(
            self.viewer
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
            DermanAccessLevel.USER,
        )

        self.assertTrue(
            visibility.can_view_content
        )

        self.assertTrue(
            visibility.can_create
        )

        dermans = list(
            visibility.dermans
        )

        self.assertEqual(
            len(dermans),
            1,
        )

        self.assertEqual(
            dermans[0]["body"],
            self.derman.body,
        )

        self.assertIsInstance(
            response.context[
                "derman_create_form"
            ],
            DermanCreateForm,
        )

    def test_complaint_owner_gets_no_create_form(
        self,
    ):
        self.client.force_login(
            self.owner
        )

        response = self.client.get(
            self.url
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
            visibility.can_create
        )

        self.assertIsNone(
            response.context[
                "derman_create_form"
            ]
        )

    def test_standard_company_context_contains_no_derman_body(
        self,
    ):
        CompanyMembership.objects.create(
            user=self.company_user,
            company=self.company,
            role=(
                CompanyMembership
                .Role
                .OWNER
            ),
            is_active=True,
        )

        self.client.force_login(
            self.company_user
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

        self.assertEqual(
            visibility.published_count,
            1,
        )

        self.assertFalse(
            visibility.can_view_content
        )

        self.assertTrue(
            visibility.paywalled
        )

        self.assertEqual(
            list(
                visibility.dermans
            ),
            [],
        )

        self.assertIsNone(
            response.context[
                "derman_create_form"
            ]
        )

    def test_pro_company_with_exact_membership_gets_body(
        self,
    ):
        CompanyMembership.objects.create(
            user=self.company_user,
            company=self.company,
            role=(
                CompanyMembership
                .Role
                .MANAGER
            ),
            is_active=True,
        )

        CompanySubscription.objects.create(
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

        self.client.force_login(
            self.company_user
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
                .COMPANY_PRO
            ),
        )

        self.assertTrue(
            visibility.can_view_content
        )

        dermans = list(
            visibility.dermans
        )

        self.assertEqual(
            len(dermans),
            1,
        )

        self.assertEqual(
            dermans[0]["body"],
            self.derman.body,
        )

        self.assertIsNone(
            response.context[
                "derman_create_form"
            ]
        )

    def test_resolved_complaint_keeps_body_but_removes_mutation_form(
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
            self.viewer
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
            visibility.can_create
        )

        self.assertFalse(
            visibility.can_react
        )

        dermans = list(
            visibility.dermans
        )

        self.assertEqual(
            len(dermans),
            1,
        )

        self.assertIsNone(
            response.context[
                "derman_create_form"
            ]
        )