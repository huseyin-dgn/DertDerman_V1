from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import Company

from .derman_selectors import (
    DermanAccessLevel,
    derman_visibility_for,
)
from .models import (
    Complaint,
    ContentReport,
    DermanPost,
    UserViolation,
)


User = get_user_model()


class DermanSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="sec-owner",
            email="sec-owner@example.com",
            user_type=User.UserType.USER,
        )
        cls.author = User.objects.create_user(
            username="sec-author",
            email="sec-author@example.com",
            user_type=User.UserType.USER,
        )
        cls.reporter = User.objects.create_user(
            username="sec-reporter",
            email="sec-reporter@example.com",
            user_type=User.UserType.USER,
        )
        cls.company_user = User.objects.create_user(
            username="sec-company",
            email="sec-company@example.com",
            user_type=User.UserType.COMPANY,
        )
        cls.admin = User.objects.create_user(
            username="sec-admin",
            email="sec-admin@example.com",
            user_type=User.UserType.ADMIN,
        )

        cls.company = Company.objects.create(
            name="Security Test Company",
            is_active=True,
            is_verified=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )

        cls.complaint = Complaint.objects.create(
            user=cls.owner,
            company=cls.company,
            title="Derman security testi",
            description=(
                "Derman security testleri için yeterince uzun "
                "şikayet açıklamasıdır."
            ),
            status=Complaint.Status.PUBLISHED,
        )

        cls.derman = DermanPost.objects.create(
            complaint=cls.complaint,
            author_user=cls.author,
            body=(
                "Derman security testleri için yeterince uzun "
                "yayınlanmış çözüm metnidir."
            ),
            status=DermanPost.Status.PUBLISHED,
            published_at=timezone.now(),
        )

    def report_url(self, complaint=None, derman=None):
        complaint = complaint or self.complaint
        derman = derman or self.derman
        return reverse(
            "complaints:derman_report",
            args=[complaint.pk, derman.pk],
        )

    def report_payload(self):
        return {
            "reason": ContentReport.Reason.SPAM,
            "description": "Security test raporu.",
        }

    def test_public_detail_is_never_cached(self):
        response = self.client.get(
            reverse(
                "complaints:public_detail",
                args=[self.complaint.pk],
            )
        )

        self.assertEqual(response.status_code, 200)

        cache_control = response.headers.get(
            "Cache-Control",
            "",
        ).lower()

        self.assertIn("no-cache", cache_control)
        self.assertIn("no-store", cache_control)
        self.assertIn("private", cache_control)

    def test_inactive_user_selector_fails_closed(self):
        self.reporter.is_active = False
        self.reporter.save(
            update_fields=("is_active",)
        )

        visibility = derman_visibility_for(
            user=self.reporter,
            complaint=self.complaint,
        )

        self.assertEqual(
            visibility.access_level,
            DermanAccessLevel.ANONYMOUS,
        )
        self.assertFalse(
            visibility.can_view_content
        )
        self.assertEqual(
            list(visibility.dermans),
            [],
        )

    def test_permanently_closed_user_selector_fails_closed(self):
        self.reporter.is_permanently_closed = True
        self.reporter.save(
            update_fields=("is_permanently_closed",)
        )

        visibility = derman_visibility_for(
            user=self.reporter,
            complaint=self.complaint,
        )

        self.assertEqual(
            visibility.access_level,
            DermanAccessLevel.ANONYMOUS,
        )
        self.assertFalse(
            visibility.can_view_content
        )
        self.assertEqual(
            list(visibility.dermans),
            [],
        )

    def test_report_endpoint_rejects_get(self):
        self.client.force_login(self.reporter)

        response = self.client.get(
            self.report_url()
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_company_and_admin_cannot_report_derman(self):
        for actor in (
            self.company_user,
            self.admin,
        ):
            with self.subTest(
                actor=actor.username
            ):
                self.client.force_login(actor)

                response = self.client.post(
                    self.report_url(),
                    self.report_payload(),
                )

                self.assertEqual(
                    response.status_code,
                    403,
                )

        self.assertFalse(
            ContentReport.objects.filter(
                derman=self.derman,
            ).exists()
        )

    def test_derman_author_cannot_report_own_derman(self):
        self.client.force_login(self.author)

        response = self.client.post(
            self.report_url(),
            self.report_payload(),
        )

        self.assertEqual(
            response.status_code,
            302,
        )
        self.assertFalse(
            ContentReport.objects.filter(
                reporter=self.author,
                derman=self.derman,
            ).exists()
        )

    def test_complaint_derman_mismatch_returns_404(self):
        other_complaint = Complaint.objects.create(
            user=self.owner,
            company=self.company,
            title="Başka security şikayeti",
            description=(
                "Başka security şikayeti için yeterince "
                "uzun açıklama metnidir."
            ),
            status=Complaint.Status.PUBLISHED,
        )

        self.client.force_login(self.reporter)

        response = self.client.post(
            self.report_url(
                complaint=other_complaint,
            ),
            self.report_payload(),
        )

        self.assertEqual(
            response.status_code,
            404,
        )
        self.assertFalse(
            ContentReport.objects.filter(
                reporter=self.reporter,
                derman=self.derman,
            ).exists()
        )

    def test_suspended_user_cannot_report_derman(self):
        self.reporter.is_suspended = True
        self.reporter.save(
            update_fields=("is_suspended",)
        )

        self.client.force_login(self.reporter)

        response = self.client.post(
            self.report_url(),
            self.report_payload(),
        )

        self.assertEqual(
            response.status_code,
            403,
        )
        self.assertFalse(
            ContentReport.objects.filter(
                reporter=self.reporter,
                derman=self.derman,
            ).exists()
        )

    def test_report_requires_csrf(self):
        client = Client(
            enforce_csrf_checks=True
        )
        client.force_login(self.reporter)

        response = client.post(
            self.report_url(),
            self.report_payload(),
        )

        self.assertEqual(
            response.status_code,
            403,
        )
        self.assertFalse(
            ContentReport.objects.filter(
                reporter=self.reporter,
                derman=self.derman,
            ).exists()
        )

    def test_duplicate_report_stays_single(self):
        self.client.force_login(self.reporter)

        self.client.post(
            self.report_url(),
            self.report_payload(),
        )
        self.client.post(
            self.report_url(),
            self.report_payload(),
        )

        self.assertEqual(
            ContentReport.objects.filter(
                reporter=self.reporter,
                derman=self.derman,
            ).count(),
            1,
        )


class DermanWithdrawnReportSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="withdraw-admin",
            email="withdraw-admin@example.com",
            user_type=User.UserType.ADMIN,
        )
        cls.owner = User.objects.create_user(
            username="withdraw-owner",
            email="withdraw-owner@example.com",
            user_type=User.UserType.USER,
        )
        cls.author = User.objects.create_user(
            username="withdraw-author",
            email="withdraw-author@example.com",
            user_type=User.UserType.USER,
        )
        cls.reporter_one = User.objects.create_user(
            username="withdraw-reporter-1",
            email="withdraw-reporter-1@example.com",
            user_type=User.UserType.USER,
        )
        cls.reporter_two = User.objects.create_user(
            username="withdraw-reporter-2",
            email="withdraw-reporter-2@example.com",
            user_type=User.UserType.USER,
        )

        cls.company = Company.objects.create(
            name="Withdraw Security Company",
            is_active=True,
            is_verified=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )

        cls.complaint = Complaint.objects.create(
            user=cls.owner,
            company=cls.company,
            title="Withdrawal security testi",
            description=(
                "Withdrawal security testleri için yeterince "
                "uzun şikayet açıklamasıdır."
            ),
            status=Complaint.Status.PUBLISHED,
        )

        cls.derman = DermanPost.objects.create(
            complaint=cls.complaint,
            author_user=cls.author,
            body=(
                "Raporlandıktan sonra geri çekilecek Derman "
                "security test içeriğidir."
            ),
            status=DermanPost.Status.PUBLISHED,
            published_at=timezone.now(),
        )

        cls.report_one = ContentReport.objects.create(
            reporter=cls.reporter_one,
            target_type=ContentReport.TargetType.DERMAN,
            derman=cls.derman,
            reason=ContentReport.Reason.HARASSMENT,
            description="Birinci Derman raporu.",
        )

        cls.report_two = ContentReport.objects.create(
            reporter=cls.reporter_two,
            target_type=ContentReport.TargetType.DERMAN,
            derman=cls.derman,
            reason=ContentReport.Reason.HARASSMENT,
            description="İkinci Derman raporu.",
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def resolve_report(self, report):
        return self.client.post(
            reverse(
                "adminx:report_status",
                kwargs={"pk": report.pk},
            ),
            {
                "status": (
                    ContentReport.Status.RESOLVED
                )
            },
        )

    def withdraw_derman(self):
        self.derman.status = (
            DermanPost.Status.WITHDRAWN
        )
        self.derman.withdrawn_at = (
            timezone.now()
        )
        self.derman.save(
            update_fields=(
                "status",
                "withdrawn_at",
            )
        )

    def test_withdrawal_does_not_escape_confirmed_violation(self):
        self.withdraw_derman()

        response = self.resolve_report(
            self.report_one
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.report_one.refresh_from_db()
        self.derman.refresh_from_db()

        self.assertEqual(
            self.report_one.status,
            ContentReport.Status.RESOLVED,
        )
        self.assertEqual(
            self.derman.status,
            DermanPost.Status.WITHDRAWN,
        )
        self.assertIsNone(
            self.derman.removed_at
        )
        self.assertIsNone(
            self.derman.removal_report_id
        )

        violation = (
            UserViolation.objects.get(
                content_report=self.report_one,
            )
        )

        self.assertEqual(
            violation.user_id,
            self.author.pk,
        )
        self.assertEqual(
            violation.source_type,
            UserViolation.SourceType.DERMAN,
        )
        self.assertEqual(
            violation.derman_id,
            self.derman.pk,
        )

    def test_multiple_resolved_reports_create_one_derman_violation(self):
        self.withdraw_derman()

        self.resolve_report(
            self.report_one
        )
        self.resolve_report(
            self.report_two
        )

        self.report_two.refresh_from_db()
        self.derman.refresh_from_db()

        self.assertEqual(
            self.report_two.status,
            ContentReport.Status.RESOLVED,
        )
        self.assertEqual(
            self.derman.status,
            DermanPost.Status.WITHDRAWN,
        )
        self.assertEqual(
            UserViolation.objects.filter(
                source_type=(
                    UserViolation.SourceType.DERMAN
                ),
                derman=self.derman,
            ).count(),
            1,
        )
