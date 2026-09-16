from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import (
    Company,
    CompanyNotification,
)
from complaints.models import (
    Complaint,
    DermanPost,
)

from .models import AdminAuditLog


User = get_user_model()


class AdminDermanModerationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="derman-admin",
            email="derman-admin@example.com",
            user_type=User.UserType.ADMIN,
        )

        cls.normal_user = User.objects.create_user(
            username="derman-normal-user",
            email="derman-normal@example.com",
            user_type=User.UserType.USER,
        )

        cls.company_user = User.objects.create_user(
            username="derman-company-user",
            email="derman-company@example.com",
            user_type=User.UserType.COMPANY,
        )

        cls.complaint_owner = User.objects.create_user(
            username="derman-complaint-owner",
            email="derman-owner@example.com",
            user_type=User.UserType.USER,
        )

        cls.derman_author = User.objects.create_user(
            username="derman-author",
            email="derman-author@example.com",
            user_type=User.UserType.USER,
        )

        cls.second_author = User.objects.create_user(
            username="derman-second-author",
            email="derman-second@example.com",
            user_type=User.UserType.USER,
        )

        cls.company = Company.objects.create(
            name="Admin Derman Test Company",
            is_active=True,
            is_verified=True,
            approval_status=(
                Company.ApprovalStatus.APPROVED
            ),
        )

        cls.complaint = Complaint.objects.create(
            user=cls.complaint_owner,
            company=cls.company,
            title="Admin Derman moderation complaint",
            description=(
                "Admin Derman moderation ekranını "
                "test etmek için yeterince uzun "
                "şikayet açıklaması."
            ),
            status=Complaint.Status.PUBLISHED,
        )

        cls.derman = DermanPost.objects.create(
            complaint=cls.complaint,
            author_user=cls.derman_author,
            body=(
                "Bu paylaşım yönetim panelindeki "
                "Derman moderasyon akışını test eder."
            ),
            status=DermanPost.Status.PENDING,
        )

        cls.published_derman = DermanPost.objects.create(
            complaint=cls.complaint,
            author_user=cls.second_author,
            body=(
                "Bu ikinci paylaşım liste filtreleme "
                "testi için yayında durumundadır."
            ),
            status=DermanPost.Status.PUBLISHED,
            published_at=timezone.now(),
        )

    def login_admin(self):
        self.client.force_login(
            self.admin
        )

    def test_derman_pages_are_admin_only(self):
        list_url = reverse(
            "adminx:derman_list"
        )

        detail_url = reverse(
            "adminx:derman_detail",
            kwargs={
                "pk": self.derman.pk,
            },
        )

        anonymous = self.client.get(
            list_url
        )

        self.assertEqual(
            anonymous.status_code,
            302,
        )

        self.assertIn(
            "/yonetim/giris/",
            anonymous.url,
        )

        for user in (
            self.normal_user,
            self.company_user,
        ):
            with self.subTest(
                role=user.user_type
            ):
                self.client.force_login(
                    user
                )

                self.assertEqual(
                    self.client.get(
                        list_url
                    ).status_code,
                    403,
                )

                self.assertEqual(
                    self.client.get(
                        detail_url
                    ).status_code,
                    403,
                )

    def test_admin_nav_contains_derman_section_and_list_defaults_to_pending(
        self,
    ):
        self.login_admin()

        response = self.client.get(
            reverse(
                "adminx:derman_list"
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            "Dermanlar",
        )

        ids = [
            item.pk
            for item
            in response.context[
                "page_obj"
            ]
        ]

        self.assertIn(
            self.derman.pk,
            ids,
        )

        self.assertNotIn(
            self.published_derman.pk,
            ids,
        )

        self.assertEqual(
            response.context[
                "filter_form"
            ].cleaned_data[
                "status"
            ],
            DermanPost.Status.PENDING,
        )

    def test_admin_can_filter_published_dermans(
        self,
    ):
        self.login_admin()

        response = self.client.get(
            reverse(
                "adminx:derman_list"
            ),
            {
                "status":
                    DermanPost
                    .Status
                    .PUBLISHED,
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        ids = [
            item.pk
            for item
            in response.context[
                "page_obj"
            ]
        ]

        self.assertIn(
            self.published_derman.pk,
            ids,
        )

        self.assertNotIn(
            self.derman.pk,
            ids,
        )

    def test_derman_detail_contains_expected_information(
        self,
    ):
        self.login_admin()

        response = self.client.get(
            reverse(
                "adminx:derman_detail",
                kwargs={
                    "pk": self.derman.pk,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            self.derman.body,
        )

        self.assertContains(
            response,
            self.derman_author.username,
        )

        self.assertContains(
            response,
            self.complaint.title,
        )

        self.assertContains(
            response,
            self.company.name,
        )

        self.assertContains(
            response,
            "Yayınla",
        )

        self.assertContains(
            response,
            "Reddet",
        )

    def test_publish_is_post_only_and_creates_audit_and_notification(
        self,
    ):
        self.login_admin()

        publish_url = reverse(
            "adminx:derman_publish",
            kwargs={
                "pk": self.derman.pk,
            },
        )

        self.assertEqual(
            self.client.get(
                publish_url
            ).status_code,
            405,
        )

        response = self.client.post(
            publish_url,
            {
                "moderation_note":
                    "İçerik uygun bulundu.",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "adminx:derman_detail",
                kwargs={
                    "pk": self.derman.pk,
                },
            ),
        )

        self.derman.refresh_from_db()

        self.assertEqual(
            self.derman.status,
            DermanPost.Status.PUBLISHED,
        )

        self.assertEqual(
            self.derman.reviewed_by_id,
            self.admin.pk,
        )

        self.assertEqual(
            self.derman.moderation_note,
            "İçerik uygun bulundu.",
        )

        audit = (
            AdminAuditLog.objects
            .get(
                target_type="derman_post",
                target_id=str(
                    self.derman.pk
                ),
                action=(
                    AdminAuditLog
                    .Action
                    .PUBLISH
                ),
            )
        )

        self.assertEqual(
            audit.actor_id,
            self.admin.pk,
        )

        notification = (
            CompanyNotification.objects
            .get(
                event_key=(
                    f"derman:"
                    f"{self.derman.pk}:"
                    "published:company"
                )
            )
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

    def test_reject_requires_moderation_note(
        self,
    ):
        self.login_admin()

        response = self.client.post(
            reverse(
                "adminx:derman_reject",
                kwargs={
                    "pk": self.derman.pk,
                },
            ),
            {
                "moderation_note": "",
            },
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        self.derman.refresh_from_db()

        self.assertEqual(
            self.derman.status,
            DermanPost.Status.PENDING,
        )

        self.assertFalse(
            AdminAuditLog.objects
            .filter(
                target_type="derman_post",
                target_id=str(
                    self.derman.pk
                ),
                action=(
                    AdminAuditLog
                    .Action
                    .REJECT
                ),
            )
            .exists()
        )

    def test_admin_can_reject_derman_and_audit_is_created(
        self,
    ):
        self.login_admin()

        response = self.client.post(
            reverse(
                "adminx:derman_reject",
                kwargs={
                    "pk": self.derman.pk,
                },
            ),
            {
                "moderation_note":
                    "Yayın kriterlerini karşılamıyor.",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "adminx:derman_detail",
                kwargs={
                    "pk": self.derman.pk,
                },
            ),
        )

        self.derman.refresh_from_db()

        self.assertEqual(
            self.derman.status,
            DermanPost.Status.REJECTED,
        )

        self.assertEqual(
            self.derman.reviewed_by_id,
            self.admin.pk,
        )

        self.assertEqual(
            self.derman.moderation_note,
            (
                "Yayın kriterlerini "
                "karşılamıyor."
            ),
        )

        self.assertTrue(
            AdminAuditLog.objects
            .filter(
                actor=self.admin,
                target_type="derman_post",
                target_id=str(
                    self.derman.pk
                ),
                action=(
                    AdminAuditLog
                    .Action
                    .REJECT
                ),
            )
            .exists()
        )

        self.assertFalse(
            CompanyNotification.objects
            .filter(
                event_key=(
                    f"derman:"
                    f"{self.derman.pk}:"
                    "published:company"
                )
            )
            .exists()
        )

    def test_second_moderation_attempt_returns_conflict_without_duplicate_audit(
        self,
    ):
        self.login_admin()

        publish_url = reverse(
            "adminx:derman_publish",
            kwargs={
                "pk": self.derman.pk,
            },
        )

        first = self.client.post(
            publish_url,
            {
                "moderation_note":
                    "İlk karar.",
            },
        )

        self.assertEqual(
            first.status_code,
            302,
        )

        second = self.client.post(
            publish_url,
            {
                "moderation_note":
                    "İkinci karar.",
            },
        )

        self.assertEqual(
            second.status_code,
            409,
        )

        self.assertEqual(
            AdminAuditLog.objects
            .filter(
                target_type="derman_post",
                target_id=str(
                    self.derman.pk
                ),
                action=(
                    AdminAuditLog
                    .Action
                    .PUBLISH
                ),
            )
            .count(),
            1,
        )

        self.assertEqual(
            CompanyNotification.objects
            .filter(
                event_key=(
                    f"derman:"
                    f"{self.derman.pk}:"
                    "published:company"
                )
            )
            .count(),
            1,
        )

    def test_resolved_parent_prevents_publish_from_admin_ui(
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

        self.login_admin()

        response = self.client.post(
            reverse(
                "adminx:derman_publish",
                kwargs={
                    "pk": self.derman.pk,
                },
            ),
            {
                "moderation_note":
                    "Yayın denemesi.",
            },
        )

        self.assertEqual(
            response.status_code,
            409,
        )

        self.derman.refresh_from_db()

        self.assertEqual(
            self.derman.status,
            DermanPost.Status.PENDING,
        )

        self.assertFalse(
            AdminAuditLog.objects
            .filter(
                target_type="derman_post",
                target_id=str(
                    self.derman.pk
                ),
                action=(
                    AdminAuditLog
                    .Action
                    .PUBLISH
                ),
            )
            .exists()
        )

    def test_publish_endpoint_requires_csrf(
        self,
    ):
        client = Client(
            enforce_csrf_checks=True
        )

        client.force_login(
            self.admin
        )

        publish_url = reverse(
            "adminx:derman_publish",
            kwargs={
                "pk": self.derman.pk,
            },
        )

        response = client.post(
            publish_url,
            {
                "moderation_note":
                    "CSRF olmadan yayınlama.",
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.derman.refresh_from_db()

        self.assertEqual(
            self.derman.status,
            DermanPost.Status.PENDING,
        )