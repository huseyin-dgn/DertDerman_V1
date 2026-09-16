from datetime import timedelta

from django.contrib.auth import (
    get_user_model,
)
from django.core.exceptions import (
    PermissionDenied,
)
from django.test import TestCase
from django.utils import timezone

from companies.models import (
    Company,
    CompanyNotification,
    CompanySubscription,
)

from .derman_moderation import (
    DermanModerationStateConflict,
    publish_derman,
    reject_derman,
)
from .models import (
    Complaint,
    DermanPost,
)


User = get_user_model()


class DermanModerationTests(
    TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls.complaint_owner = (
            User.objects.create_user(
                username=(
                    "derman-mod-owner"
                ),
                email=(
                    "derman-mod-owner"
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
                    "derman-mod-author"
                ),
                email=(
                    "derman-mod-author"
                    "@example.com"
                ),
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.admin = (
            User.objects.create_user(
                username=(
                    "derman-mod-admin"
                ),
                email=(
                    "derman-mod-admin"
                    "@example.com"
                ),
                user_type=(
                    User.UserType.ADMIN
                ),
            )
        )

        cls.normal_user = (
            User.objects.create_user(
                username=(
                    "derman-mod-normal"
                ),
                email=(
                    "derman-mod-normal"
                    "@example.com"
                ),
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.company = (
            Company.objects.create(
                name=(
                    "Derman Moderation "
                    "Company"
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
                user=cls.complaint_owner,
                company=cls.company,
                title=(
                    "Derman moderation "
                    "şikayeti"
                ),
                description=(
                    "Derman moderation "
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
                    "Bu Derman moderation "
                    "testleri için kullanılan "
                    "gizli çözüm içeriğidir."
                ),
                status=(
                    DermanPost.Status.PENDING
                ),
            )
        )

    def test_publish_sets_review_fields_and_creates_company_notification_without_body(
        self,
    ):
        derman, notification = (
            publish_derman(
                derman_id=self.derman.pk,
                actor=self.admin,
                moderation_note=(
                    "İçerik uygun bulundu."
                ),
            )
        )

        derman.refresh_from_db()

        self.assertEqual(
            derman.status,
            DermanPost.Status.PUBLISHED,
        )

        self.assertIsNotNone(
            derman.published_at
        )

        self.assertIsNotNone(
            derman.reviewed_at
        )

        self.assertEqual(
            derman.reviewed_by_id,
            self.admin.pk,
        )

        self.assertEqual(
            derman.moderation_note,
            "İçerik uygun bulundu.",
        )

        self.assertEqual(
            notification.company_id,
            self.company.pk,
        )

        self.assertEqual(
            notification.complaint_id,
            self.complaint.pk,
        )

        self.assertEqual(
            notification.kind,
            CompanyNotification.Kind.DERMAN,
        )

        self.assertNotIn(
            self.derman.body,
            notification.title,
        )

        self.assertNotIn(
            self.derman.body,
            notification.message,
        )

    def test_standard_company_notification_mentions_pro_without_body(
        self,
    ):
        _, notification = (
            publish_derman(
                derman_id=self.derman.pk,
                actor=self.admin,
            )
        )

        self.assertIn(
            "DertDerman Pro",
            notification.message,
        )

        self.assertNotIn(
            self.derman.body,
            notification.message,
        )

    def test_pro_company_notification_still_contains_no_derman_body(
        self,
    ):
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

        _, notification = (
            publish_derman(
                derman_id=self.derman.pk,
                actor=self.admin,
            )
        )

        self.assertNotIn(
            self.derman.body,
            notification.title,
        )

        self.assertNotIn(
            self.derman.body,
            notification.message,
        )

        self.assertNotIn(
            "DertDerman Pro'yu",
            notification.message,
        )

    def test_reject_does_not_create_company_notification(
        self,
    ):
        derman = reject_derman(
            derman_id=self.derman.pk,
            actor=self.admin,
            moderation_note=(
                "Yayın kriterlerini "
                "karşılamıyor."
            ),
        )

        derman.refresh_from_db()

        self.assertEqual(
            derman.status,
            DermanPost.Status.REJECTED,
        )

        self.assertEqual(
            derman.reviewed_by_id,
            self.admin.pk,
        )

        self.assertFalse(
            CompanyNotification.objects
            .filter(
                event_key=(
                    f"derman:{derman.pk}:"
                    "published:company"
                )
            )
            .exists()
        )

    def test_resolved_parent_blocks_publish(
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

        with self.assertRaises(
            DermanModerationStateConflict
        ):
            publish_derman(
                derman_id=self.derman.pk,
                actor=self.admin,
            )

        self.derman.refresh_from_db()

        self.assertEqual(
            self.derman.status,
            DermanPost.Status.PENDING,
        )

        self.assertFalse(
            CompanyNotification.objects
            .filter(
                kind=(
                    CompanyNotification
                    .Kind
                    .DERMAN
                )
            )
            .exists()
        )

    def test_withdrawn_parent_blocks_publish(
        self,
    ):
        self.complaint.withdrawn_at = (
            timezone.now()
        )

        self.complaint.save(
            update_fields=(
                "withdrawn_at",
                "updated_at",
            )
        )

        with self.assertRaises(
            DermanModerationStateConflict
        ):
            publish_derman(
                derman_id=self.derman.pk,
                actor=self.admin,
            )

        self.derman.refresh_from_db()

        self.assertEqual(
            self.derman.status,
            DermanPost.Status.PENDING,
        )

    def test_non_admin_cannot_moderate(
        self,
    ):
        with self.assertRaises(
            PermissionDenied
        ):
            publish_derman(
                derman_id=self.derman.pk,
                actor=self.normal_user,
            )

        self.derman.refresh_from_db()

        self.assertEqual(
            self.derman.status,
            DermanPost.Status.PENDING,
        )

    def test_second_publish_is_blocked_and_notification_is_not_duplicated(
        self,
    ):
        publish_derman(
            derman_id=self.derman.pk,
            actor=self.admin,
        )

        with self.assertRaises(
            DermanModerationStateConflict
        ):
            publish_derman(
                derman_id=self.derman.pk,
                actor=self.admin,
            )

        self.assertEqual(
            CompanyNotification.objects
            .filter(
                event_key=(
                    f"derman:{self.derman.pk}:"
                    "published:company"
                )
            )
            .count(),
            1,
        )