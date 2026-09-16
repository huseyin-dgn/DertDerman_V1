from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from companies.models import (
    Company,
    CompanyMembership,
    CompanySubscription,
)

from .derman_selectors import (
    DermanAccessLevel,
    derman_visibility_for,
)
from .models import (
    Complaint,
    DermanPost,
)


User = get_user_model()


class DermanSelectorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="selector-owner",
            email="selector-owner@example.com",
            user_type=User.UserType.USER,
        )

        cls.viewer = User.objects.create_user(
            username="selector-viewer",
            email="selector-viewer@example.com",
            user_type=User.UserType.USER,
        )

        cls.derman_author = User.objects.create_user(
            username="selector-derman-author",
            email="selector-derman-author@example.com",
            user_type=User.UserType.USER,
        )

        cls.pending_author = User.objects.create_user(
            username="selector-pending-author",
            email="selector-pending-author@example.com",
            user_type=User.UserType.USER,
        )

        cls.rejected_author = User.objects.create_user(
            username="selector-rejected-author",
            email="selector-rejected-author@example.com",
            user_type=User.UserType.USER,
        )

        cls.withdrawn_author = User.objects.create_user(
            username="selector-withdrawn-author",
            email="selector-withdrawn-author@example.com",
            user_type=User.UserType.USER,
        )

        cls.removed_author = User.objects.create_user(
            username="selector-removed-author",
            email="selector-removed-author@example.com",
            user_type=User.UserType.USER,
        )

        cls.company_user = User.objects.create_user(
            username="selector-company-user",
            email="selector-company-user@example.com",
            user_type=User.UserType.COMPANY,
        )

        cls.other_company_user = User.objects.create_user(
            username="selector-other-company-user",
            email="selector-other-company-user@example.com",
            user_type=User.UserType.COMPANY,
        )

        cls.admin = User.objects.create_user(
            username="selector-admin",
            email="selector-admin@example.com",
            user_type=User.UserType.ADMIN,
        )

        cls.company = Company.objects.create(
            name="Selector Company",
            is_active=True,
            is_verified=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )

        cls.other_company = Company.objects.create(
            name="Other Selector Company",
            is_active=True,
            is_verified=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )

        cls.complaint = Complaint.objects.create(
            user=cls.owner,
            company=cls.company,
            title="Selector test şikayeti",
            description=(
                "Selector görünürlük testleri için "
                "yeterince uzun şikayet açıklaması."
            ),
            status=Complaint.Status.PUBLISHED,
        )

        cls.published_derman = DermanPost.objects.create(
            complaint=cls.complaint,
            author_user=cls.derman_author,
            body=(
                "Bu yayınlanmış Derman içeriği "
                "selector testleri için yeterince "
                "uzun bir açıklamadır."
            ),
            status=DermanPost.Status.PUBLISHED,
            published_at=timezone.now(),
        )

        DermanPost.objects.create(
            complaint=cls.complaint,
            author_user=cls.pending_author,
            body=(
                "Bu pending Derman içeriği "
                "görünür olmamalıdır."
            ),
            status=DermanPost.Status.PENDING,
        )

        DermanPost.objects.create(
            complaint=cls.complaint,
            author_user=cls.rejected_author,
            body=(
                "Bu rejected Derman içeriği "
                "görünür olmamalıdır."
            ),
            status=DermanPost.Status.REJECTED,
        )

        DermanPost.objects.create(
            complaint=cls.complaint,
            author_user=cls.withdrawn_author,
            body=(
                "Bu withdrawn Derman içeriği "
                "görünür olmamalıdır."
            ),
            status=DermanPost.Status.WITHDRAWN,
            withdrawn_at=timezone.now(),
        )

        DermanPost.objects.create(
            complaint=cls.complaint,
            author_user=cls.removed_author,
            body=(
                "Bu removed Derman içeriği "
                "görünür olmamalıdır."
            ),
            status=DermanPost.Status.REMOVED,
            removed_at=timezone.now(),
            removal_reason="Selector test kaldırma nedeni.",
        )

    def test_anonymous_only_gets_published_count(self):
        visibility = derman_visibility_for(
            user=None,
            complaint=self.complaint,
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
        self.assertFalse(
            visibility.paywalled
        )
        self.assertFalse(
            visibility.can_create
        )
        self.assertFalse(
            visibility.can_react
        )
        self.assertEqual(
            list(visibility.dermans),
            [],
        )

    def test_user_can_view_only_published_dermans(self):
        visibility = derman_visibility_for(
            user=self.viewer,
            complaint=self.complaint,
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
        self.assertTrue(
            visibility.can_react
        )

        dermans = list(
            visibility.dermans
        )

        self.assertEqual(
            len(dermans),
            1,
        )
        self.assertEqual(
            dermans[0]["id"],
            self.published_derman.pk,
        )
        self.assertEqual(
            dermans[0]["body"],
            self.published_derman.body,
        )

    def test_complaint_owner_cannot_create_derman(self):
        visibility = derman_visibility_for(
            user=self.owner,
            complaint=self.complaint,
        )

        self.assertFalse(
            visibility.can_create
        )
        self.assertTrue(
            visibility.can_view_content
        )

    def test_existing_derman_blocks_lifetime_creation(self):
        DermanPost.objects.create(
            complaint=self.complaint,
            author_user=self.viewer,
            body=(
                "Bu kullanıcı daha önce Derman "
                "paylaştığı için tekrar "
                "oluşturamamalıdır."
            ),
            status=DermanPost.Status.WITHDRAWN,
            withdrawn_at=timezone.now(),
        )

        visibility = derman_visibility_for(
            user=self.viewer,
            complaint=self.complaint,
        )

        self.assertFalse(
            visibility.can_create
        )

    def test_standard_company_only_gets_count_and_paywall(self):
        CompanyMembership.objects.create(
            user=self.company_user,
            company=self.company,
            role=CompanyMembership.Role.OWNER,
            is_active=True,
        )

        visibility = derman_visibility_for(
            user=self.company_user,
            complaint=self.complaint,
        )

        self.assertEqual(
            visibility.access_level,
            DermanAccessLevel.COMPANY_STANDARD,
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
            list(visibility.dermans),
            [],
        )

    def test_standard_company_with_zero_dermans_has_no_paywall(self):
        CompanyMembership.objects.create(
            user=self.company_user,
            company=self.company,
            role=CompanyMembership.Role.OWNER,
            is_active=True,
        )

        self.published_derman.status = (
            DermanPost.Status.REMOVED
        )
        self.published_derman.removed_at = (
            timezone.now()
        )
        self.published_derman.removal_reason = (
            "Selector test."
        )
        self.published_derman.save()

        visibility = derman_visibility_for(
            user=self.company_user,
            complaint=self.complaint,
        )

        self.assertEqual(
            visibility.published_count,
            0,
        )
        self.assertFalse(
            visibility.paywalled
        )
        self.assertEqual(
            list(visibility.dermans),
            [],
        )

    def test_pro_company_with_exact_membership_can_view_content(self):
        CompanyMembership.objects.create(
            user=self.company_user,
            company=self.company,
            role=CompanyMembership.Role.MANAGER,
            is_active=True,
        )

        CompanySubscription.objects.create(
            company=self.company,
            plan=CompanySubscription.Plan.PRO,
            billing_period=(
                CompanySubscription.BillingPeriod.MONTHLY
            ),
            is_active=True,
            current_period_end=(
                timezone.now()
                + timedelta(days=30)
            ),
        )

        visibility = derman_visibility_for(
            user=self.company_user,
            complaint=self.complaint,
        )

        self.assertEqual(
            visibility.access_level,
            DermanAccessLevel.COMPANY_PRO,
        )
        self.assertTrue(
            visibility.can_view_content
        )
        self.assertFalse(
            visibility.paywalled
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
        self.assertEqual(
            dermans[0]["body"],
            self.published_derman.body,
        )

    def test_pro_subscription_without_exact_membership_does_not_grant_access(
        self,
    ):
        CompanyMembership.objects.create(
            user=self.other_company_user,
            company=self.other_company,
            role=CompanyMembership.Role.OWNER,
            is_active=True,
        )

        CompanySubscription.objects.create(
            company=self.company,
            plan=CompanySubscription.Plan.PRO,
            billing_period=(
                CompanySubscription.BillingPeriod.MONTHLY
            ),
            is_active=True,
            current_period_end=(
                timezone.now()
                + timedelta(days=30)
            ),
        )

        visibility = derman_visibility_for(
            user=self.other_company_user,
            complaint=self.complaint,
        )

        self.assertEqual(
            visibility.access_level,
            DermanAccessLevel.COMPANY_STANDARD,
        )
        self.assertFalse(
            visibility.can_view_content
        )
        self.assertTrue(
            visibility.paywalled
        )
        self.assertEqual(
            list(visibility.dermans),
            [],
        )

    def test_expired_pro_subscription_does_not_grant_access(
        self,
    ):
        CompanyMembership.objects.create(
            user=self.company_user,
            company=self.company,
            role=CompanyMembership.Role.OWNER,
            is_active=True,
        )

        CompanySubscription.objects.create(
            company=self.company,
            plan=CompanySubscription.Plan.PRO,
            billing_period=(
                CompanySubscription.BillingPeriod.MONTHLY
            ),
            is_active=True,
            current_period_end=(
                timezone.now()
                - timedelta(seconds=1)
            ),
        )

        visibility = derman_visibility_for(
            user=self.company_user,
            complaint=self.complaint,
        )

        self.assertEqual(
            visibility.access_level,
            DermanAccessLevel.COMPANY_STANDARD,
        )
        self.assertFalse(
            visibility.can_view_content
        )
        self.assertTrue(
            visibility.paywalled
        )
        self.assertEqual(
            list(visibility.dermans),
            [],
        )

    def test_admin_can_view_published_content(self):
        visibility = derman_visibility_for(
            user=self.admin,
            complaint=self.complaint,
        )

        self.assertEqual(
            visibility.access_level,
            DermanAccessLevel.ADMIN,
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

    def test_resolved_complaint_keeps_published_derman_visible_but_read_only(
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

        visibility = derman_visibility_for(
            user=self.viewer,
            complaint=self.complaint,
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
        self.assertEqual(
            dermans[0]["id"],
            self.published_derman.pk,
        )

    def test_only_published_status_counts(self):
        visibility = derman_visibility_for(
            user=None,
            complaint=self.complaint,
        )

        self.assertEqual(
            visibility.published_count,
            1,
        )