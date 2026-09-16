from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import (
    Company,
    CompanyMembership,
    CompanyNotification,
    CompanySubscription,
)
from complaints.derman_company_services import (
    create_derman_company_response,
    update_derman_company_response,
)
from complaints.derman_moderation import (
    publish_derman,
    reject_derman,
)
from complaints.derman_services import toggle_derman_reaction
from complaints.models import (
    Complaint,
    ContentReport,
    DermanPost,
    DermanReaction,
    UserViolation,
)
from notifications.models import EmailOutbox, Notification
from notifications.transactional_email import render_notification_outbox

from .models import AdminAuditLog


User = get_user_model()


class AdminDermanReportingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="derman-report-admin",
            email="derman-report-admin@example.com",
            user_type=User.UserType.ADMIN,
            is_verified=True,
        )
        cls.owner = User.objects.create_user(
            username="derman-report-owner",
            email="derman-report-owner@example.com",
            user_type=User.UserType.USER,
            is_verified=True,
        )
        cls.author = User.objects.create_user(
            username="derman-report-author",
            email="derman-report-author@example.com",
            user_type=User.UserType.USER,
            is_verified=True,
        )
        cls.reporter = User.objects.create_user(
            username="derman-report-reporter",
            email="derman-report-reporter@example.com",
            user_type=User.UserType.USER,
            is_verified=True,
        )
        cls.company_user = User.objects.create_user(
            username="derman-report-company",
            email="derman-report-company@example.com",
            user_type=User.UserType.COMPANY,
            is_verified=True,
        )
        cls.company = Company.objects.create(
            name="Derman Reporting Company",
            is_active=True,
            is_verified=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )
        cls.other_company = Company.objects.create(
            name="Unrelated Reporting Company",
            is_active=True,
            is_verified=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )
        cls.complaint = Complaint.objects.create(
            user=cls.owner,
            company=cls.company,
            title="Derman reporting complaint",
            description=(
                "Derman reporting testleri için yeterince uzun açıklama."
            ),
            status=Complaint.Status.PUBLISHED,
        )
        cls.derman = DermanPost.objects.create(
            complaint=cls.complaint,
            author_user=cls.author,
            body=(
                "Yalnız moderasyon ekranında ve yetkili Derman "
                "görünümünde bulunması gereken benzersiz içerik."
            ),
            status=DermanPost.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        cls.report = ContentReport.objects.create(
            reporter=cls.reporter,
            target_type=ContentReport.TargetType.DERMAN,
            derman=cls.derman,
            reason=ContentReport.Reason.HARASSMENT,
            description="Derman raporu için kullanıcı açıklaması.",
        )
        CompanyMembership.objects.create(
            user=cls.company_user,
            company=cls.company,
            role=CompanyMembership.Role.OWNER,
            is_active=True,
        )
        CompanySubscription.objects.create(
            company=cls.company,
            plan=CompanySubscription.Plan.PRO,
            billing_period=CompanySubscription.BillingPeriod.MONTHLY,
            is_active=True,
            current_period_end=timezone.now() + timedelta(days=30),
        )

    def setUp(self):
        EmailOutbox.objects.all().delete()
        Notification.objects.all().delete()
        CompanyNotification.objects.all().delete()
        self.client.force_login(self.admin)

    def _status_url(self):
        return reverse(
            "adminx:report_status",
            kwargs={"pk": self.report.pk},
        )

    def _post_status(self, status):
        return self.client.post(
            self._status_url(),
            {"status": status},
        )

    def test_derman_report_list_and_search_show_target_preview(self):
        list_url = reverse("adminx:report_list")

        response = self.client.get(list_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Derman Ol")
        self.assertContains(response, f"#{self.derman.pk}")
        self.assertContains(response, self.derman.body[:40])

        search_response = self.client.get(
            list_url,
            {"q": "benzersiz içerik", "status": "all"},
        )
        self.assertContains(search_response, f"#{self.derman.pk}")

    def test_derman_report_detail_shows_context_and_admin_links(self):
        response = self.client.get(
            reverse(
                "adminx:report_detail",
                kwargs={"pk": self.report.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Derman #{self.derman.pk}")
        self.assertContains(response, self.derman.body)
        self.assertContains(response, f"@{self.author.username}")
        self.assertContains(response, self.derman.get_status_display())
        self.assertContains(response, self.complaint.title)
        self.assertContains(response, self.company.name)
        self.assertContains(
            response,
            reverse("adminx:complaint_detail", args=[self.complaint.pk]),
        )
        self.assertContains(
            response,
            reverse("adminx:derman_detail", args=[self.derman.pk]),
        )
        self.assertContains(
            response,
            reverse("complaints:public_detail", args=[self.complaint.pk]),
        )
        self.assertNotContains(response, "Raporlanan içerik türü tanınmıyor")

    def test_resolved_removes_derman_and_creates_author_violation(self):
        response = self._post_status(ContentReport.Status.RESOLVED)
        self.assertRedirects(
            response,
            reverse("adminx:report_detail", args=[self.report.pk]),
        )

        self.report.refresh_from_db()
        self.derman.refresh_from_db()
        self.assertEqual(self.report.status, ContentReport.Status.RESOLVED)
        self.assertEqual(self.derman.status, DermanPost.Status.REMOVED)
        self.assertIsNotNone(self.derman.removed_at)
        self.assertEqual(self.derman.removed_by_id, self.admin.pk)
        self.assertEqual(self.derman.removal_reason, self.report.reason)
        self.assertEqual(self.derman.removal_report_id, self.report.pk)

        violation = UserViolation.objects.get(content_report=self.report)
        self.assertEqual(violation.user_id, self.author.pk)
        self.assertEqual(violation.source_type, UserViolation.SourceType.DERMAN)
        self.assertEqual(violation.derman_id, self.derman.pk)
        self.assertNotEqual(violation.user_id, self.reporter.pk)

        derman_audit = AdminAuditLog.objects.get(
            target_type="derman_post",
            target_id=str(self.derman.pk),
        )
        self.assertEqual(
            derman_audit.metadata["previous_status"],
            DermanPost.Status.PUBLISHED,
        )
        self.assertEqual(
            derman_audit.metadata["new_status"],
            DermanPost.Status.REMOVED,
        )
        self.assertEqual(
            derman_audit.metadata["complaint_id"],
            self.complaint.pk,
        )

        report_audit = AdminAuditLog.objects.filter(
            target_type="content_report",
            target_id=str(self.report.pk),
        ).latest("pk")
        self.assertTrue(report_audit.metadata["derman_removed"])
        self.assertEqual(report_audit.metadata["derman_id"], self.derman.pk)
        self.assertEqual(
            report_audit.metadata["user_violation_id"],
            violation.pk,
        )

        removal_notification = Notification.objects.get(
            event_key=(
                f"derman:{self.derman.pk}:removed:"
                f"report:{self.report.pk}:author"
            )
        )
        self.assertEqual(removal_notification.recipient_user_id, self.author.pk)
        self.assertNotIn(self.derman.body, removal_notification.message)
        self.assertTrue(
            EmailOutbox.objects.filter(notification=removal_notification).exists()
        )

    def test_resolved_retry_is_idempotent(self):
        self._post_status(ContentReport.Status.RESOLVED)
        removed_at = DermanPost.objects.get(pk=self.derman.pk).removed_at
        violation_count = UserViolation.objects.filter(
            content_report=self.report
        ).count()
        audit_count = AdminAuditLog.objects.filter(
            target_type="derman_post",
            target_id=str(self.derman.pk),
        ).count()
        notification_count = Notification.objects.filter(
            event_key=(
                f"derman:{self.derman.pk}:removed:"
                f"report:{self.report.pk}:author"
            )
        ).count()

        self._post_status(ContentReport.Status.RESOLVED)
        self.derman.refresh_from_db()

        self.assertEqual(self.derman.removed_at, removed_at)
        self.assertEqual(
            UserViolation.objects.filter(content_report=self.report).count(),
            violation_count,
        )
        self.assertEqual(
            AdminAuditLog.objects.filter(
                target_type="derman_post",
                target_id=str(self.derman.pk),
            ).count(),
            audit_count,
        )
        self.assertEqual(
            Notification.objects.filter(
                event_key=(
                    f"derman:{self.derman.pk}:removed:"
                    f"report:{self.report.pk}:author"
                )
            ).count(),
            notification_count,
        )

    def test_rejected_report_does_not_change_derman(self):
        self._post_status(ContentReport.Status.REJECTED)
        self.report.refresh_from_db()
        self.derman.refresh_from_db()

        self.assertEqual(self.report.status, ContentReport.Status.REJECTED)
        self.assertEqual(self.derman.status, DermanPost.Status.PUBLISHED)
        self.assertIsNone(self.derman.removed_at)
        self.assertFalse(
            UserViolation.objects.filter(content_report=self.report).exists()
        )

    def test_abusive_report_preserves_derman_and_penalizes_reporter(self):
        self._post_status(ContentReport.Status.ABUSIVE)
        self.derman.refresh_from_db()

        self.assertEqual(self.derman.status, DermanPost.Status.PUBLISHED)
        violation = UserViolation.objects.get(content_report=self.report)
        self.assertEqual(violation.user_id, self.reporter.pk)
        self.assertEqual(
            violation.source_type,
            UserViolation.SourceType.FALSE_REPORT,
        )

    def test_terminal_report_decision_cannot_be_changed(self):
        self._post_status(ContentReport.Status.RESOLVED)
        violation_count = UserViolation.objects.filter(
            content_report=self.report
        ).count()

        self._post_status(ContentReport.Status.REJECTED)
        self.report.refresh_from_db()

        self.assertEqual(self.report.status, ContentReport.Status.RESOLVED)
        self.assertEqual(
            UserViolation.objects.filter(content_report=self.report).count(),
            violation_count,
        )

    def test_resolved_does_not_remove_non_published_derman(self):
        self.derman.status = DermanPost.Status.REJECTED
        self.derman.save(update_fields=("status",))

        self._post_status(ContentReport.Status.RESOLVED)
        self.derman.refresh_from_db()

        self.assertEqual(self.derman.status, DermanPost.Status.REJECTED)
        self.assertIsNone(self.derman.removed_at)
        self.assertFalse(
            UserViolation.objects.filter(content_report=self.report).exists()
        )

    def test_publish_notifies_author_owner_and_exact_company_without_body(self):
        self.derman.status = DermanPost.Status.PENDING
        self.derman.published_at = None
        self.derman.save(update_fields=("status", "published_at"))

        publish_derman(derman_id=self.derman.pk, actor=self.admin)

        author_notification = Notification.objects.get(
            event_key=f"derman:{self.derman.pk}:published:author"
        )
        owner_notification = Notification.objects.get(
            event_key=(
                f"derman:{self.derman.pk}:published:complaint-owner"
            )
        )
        self.assertEqual(author_notification.recipient_user_id, self.author.pk)
        self.assertEqual(owner_notification.recipient_user_id, self.owner.pk)
        self.assertNotIn(self.derman.body, author_notification.message)
        self.assertNotIn(self.derman.body, owner_notification.message)

        company_notification = CompanyNotification.objects.get(
            event_key=f"derman:{self.derman.pk}:published:company"
        )
        self.assertEqual(company_notification.company_id, self.company.pk)
        self.assertNotEqual(company_notification.company_id, self.other_company.pk)
        self.assertNotIn(self.derman.body, company_notification.message)

        outboxes = EmailOutbox.objects.filter(
            notification__in=(author_notification, owner_notification)
        )
        self.assertEqual(outboxes.count(), 2)
        for outbox in outboxes:
            payload = render_notification_outbox(outbox)
            self.assertNotIn(self.derman.body, payload.html_body)
            self.assertNotIn(self.derman.body, payload.text_body)

    def test_reject_notifies_author_without_body_or_internal_note(self):
        self.derman.status = DermanPost.Status.PENDING
        self.derman.published_at = None
        self.derman.save(update_fields=("status", "published_at"))
        internal_note = "Hassas yalnız yönetici notu"

        reject_derman(
            derman_id=self.derman.pk,
            actor=self.admin,
            moderation_note=internal_note,
        )

        notification = Notification.objects.get(
            event_key=f"derman:{self.derman.pk}:rejected:author"
        )
        self.assertEqual(notification.recipient_user_id, self.author.pk)
        self.assertNotIn(self.derman.body, notification.message)
        self.assertNotIn(internal_note, notification.message)
        self.assertTrue(
            EmailOutbox.objects.filter(notification=notification).exists()
        )

    def test_company_response_create_notifies_author_but_update_does_not_spam(self):
        response = create_derman_company_response(
            derman_id=self.derman.pk,
            actor=self.company_user,
            body=(
                "Şirketin Derman için oluşturduğu ilk resmi yanıt metnidir."
            ),
        )
        event_key = f"derman-response:{response.pk}:created:author"
        notification = Notification.objects.get(event_key=event_key)
        self.assertEqual(notification.recipient_user_id, self.author.pk)
        self.assertNotIn(response.body, notification.message)
        self.assertEqual(
            EmailOutbox.objects.filter(notification=notification).count(),
            1,
        )

        update_derman_company_response(
            derman_id=self.derman.pk,
            actor=self.company_user,
            body=(
                "Şirketin Derman için güncellediği resmi yanıt metnidir."
            ),
        )

        self.assertEqual(Notification.objects.filter(event_key=event_key).count(), 1)
        self.assertEqual(
            EmailOutbox.objects.filter(notification=notification).count(),
            1,
        )

    def test_reaction_does_not_create_notification_or_email(self):
        toggle_derman_reaction(
            derman_id=self.derman.pk,
            actor=self.reporter,
            reaction_type=DermanReaction.Type.LIKE,
        )

        self.assertFalse(Notification.objects.exists())
        self.assertFalse(EmailOutbox.objects.exists())
