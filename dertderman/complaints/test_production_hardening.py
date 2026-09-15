from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from adminx.models import AdminAuditLog
from adminx.services import lock_current_admin
from accounts.badges import resolve_user_badges
from companies.badges import company_badge_facts
from companies.complaint_policy import company_can_interact_with_complaint
from companies.models import (
    Company,
    CompanyMembership,
    CompanyNotification,
    CompanyResponse,
    CompanySubscription,
)
from companies.panel_services import create_company_entry
from companies.selectors import public_company_performance
from notifications.models import Notification

from .forms import ComplaintEditForm
from .models import (
    Complaint,
    ComplaintComment,
    ComplaintEvent,
    ComplaintLike,
    CompanyReport,
    ContentReport,
    ReportRestriction,
    UserReport,
    UserViolation,
)
from .selectors import public_complaints
from .services import (
    ComplaintStateConflict,
    edit_complaint,
    resolve_complaint,
    withdraw_complaint,
)


User = get_user_model()


class ComplaintProductionHardeningTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="hardening-owner",
            email="hardening-owner@example.com",
            user_type=User.UserType.USER,
            is_verified=True,
        )
        cls.other = User.objects.create_user(
            username="hardening-other",
            email="hardening-other@example.com",
            user_type=User.UserType.USER,
            is_verified=True,
        )
        cls.admin = User.objects.create_user(
            username="hardening-admin",
            email="hardening-admin@example.com",
            user_type=User.UserType.ADMIN,
        )
        cls.company_actor = User.objects.create_user(
            username="hardening-company-actor",
            email="hardening-company-actor@example.com",
            user_type=User.UserType.COMPANY,
        )
        cls.company = Company.objects.create(
            name="Hardening Company",
            is_active=True,
            is_verified=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )
        CompanyMembership.objects.create(
            user=cls.company_actor,
            company=cls.company,
            role=CompanyMembership.Role.OWNER,
            is_active=True,
        )
        CompanySubscription.objects.create(
            company=cls.company,
            plan=CompanySubscription.Plan.PRO,
            billing_period=CompanySubscription.BillingPeriod.MONTHLY,
            is_active=True,
        )

    def complaint(self, *, owner=None, status=Complaint.Status.PUBLISHED):
        return Complaint.objects.create(
            user=owner or self.owner,
            company=self.company,
            status=status,
            title="Production hardening complaint",
            description="This complaint has sufficiently long production test content.",
        )

    def test_resolve_service_derives_user_scope_and_rejects_company_actor(self):
        foreign = self.complaint(owner=self.other)

        with self.assertRaises(Complaint.DoesNotExist):
            resolve_complaint(complaint_id=foreign.pk, actor=self.owner)

        with self.assertRaises(PermissionDenied):
            resolve_complaint(complaint_id=foreign.pk, actor=self.company_actor)

        foreign.refresh_from_db()
        self.assertEqual(foreign.status, Complaint.Status.PUBLISHED)

    def test_services_recheck_stale_suspension_state(self):
        complaint = self.complaint()
        User.objects.filter(pk=self.owner.pk).update(is_suspended=True)

        with self.assertRaises(PermissionDenied):
            withdraw_complaint(complaint=complaint, actor=self.owner)

        complaint.refresh_from_db()
        self.assertIsNone(complaint.withdrawn_at)

    def test_services_recheck_stale_role_state(self):
        complaint = self.complaint()
        User.objects.filter(pk=self.owner.pk).update(
            user_type=User.UserType.COMPANY,
        )

        with self.assertRaises(PermissionDenied):
            withdraw_complaint(complaint=complaint, actor=self.owner)

        complaint.refresh_from_db()
        self.assertIsNone(complaint.withdrawn_at)

    def test_terminal_complaints_cannot_be_withdrawn(self):
        for status in (
            Complaint.Status.REJECTED,
            Complaint.Status.RESOLVED,
            Complaint.Status.REMOVED,
        ):
            with self.subTest(status=status):
                complaint = self.complaint(status=status)
                with self.assertRaises(ComplaintStateConflict):
                    withdraw_complaint(complaint=complaint, actor=self.owner)
                complaint.refresh_from_db()
                self.assertIsNone(complaint.withdrawn_at)
                self.assertFalse(
                    complaint.timeline_events.filter(
                        event_type=ComplaintEvent.Type.WITHDRAWN,
                    ).exists()
                )

    def test_edit_uses_locked_record_and_hidden_state_notifies_no_company(self):
        complaint = self.complaint()
        CompanyNotification.objects.filter(complaint=complaint).delete()
        form = ComplaintEditForm(
            {
                "company": self.company.pk,
                "category": Complaint.Category.OTHER,
                "title": "Safely edited complaint",
                "description": "This safely edited complaint remains long enough to validate.",
            },
            instance=complaint,
        )
        self.assertTrue(form.is_valid(), form.errors)

        edit_complaint(complaint=complaint, form=form, actor=self.owner)

        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.PENDING)
        self.assertFalse(CompanyNotification.objects.filter(complaint=complaint).exists())

    def test_edit_rechecks_new_company_lifecycle_after_form_validation(self):
        complaint = self.complaint()
        replacement = Company.objects.create(
            name="Replacement Company",
            is_active=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )
        form = ComplaintEditForm(
            {
                "company": replacement.pk,
                "category": Complaint.Category.OTHER,
                "title": "Company lifecycle edit",
                "description": "This complaint edit remains long enough to validate safely.",
            },
            instance=complaint,
        )
        self.assertTrue(form.is_valid(), form.errors)
        Company.objects.filter(pk=replacement.pk).update(is_active=False)

        with self.assertRaises(ComplaintStateConflict):
            edit_complaint(complaint=complaint, form=form, actor=self.owner)

        complaint.refresh_from_db()
        self.assertEqual(complaint.company_id, self.company.pk)

    def test_stale_pending_edit_cannot_overwrite_newer_moderation(self):
        complaint = self.complaint(status=Complaint.Status.PENDING)
        form = ComplaintEditForm(
            {
                "company": self.company.pk,
                "category": Complaint.Category.OTHER,
                "title": "Stale edit must fail",
                "description": "This stale edit must not replace a newer moderation decision.",
            },
            instance=complaint,
        )
        self.assertTrue(form.is_valid(), form.errors)
        Complaint.objects.filter(pk=complaint.pk).update(
            status=Complaint.Status.PUBLISHED,
            updated_at=timezone.now() + timedelta(seconds=1),
        )

        with self.assertRaises(ComplaintStateConflict):
            edit_complaint(complaint=complaint, form=form, actor=self.owner)

        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.PUBLISHED)
        self.assertEqual(complaint.title, "Production hardening complaint")
        self.assertFalse(
            complaint.timeline_events.filter(
                event_type=ComplaintEvent.Type.EDITED,
            ).exists()
        )

    def test_private_mutations_are_owner_scoped(self):
        foreign_pending = self.complaint(
            owner=self.other,
            status=Complaint.Status.PENDING,
        )
        foreign_public = self.complaint(owner=self.other)
        self.client.force_login(self.owner)

        self.assertEqual(
            self.client.get(
                reverse("complaints:detail", args=[foreign_pending.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("complaints:edit", args=[foreign_pending.pk]),
                {
                    "company": self.company.pk,
                    "category": Complaint.Category.OTHER,
                    "title": "Cross-owner edit",
                    "description": "This cross-owner edit must never be persisted.",
                },
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("complaints:withdraw", args=[foreign_pending.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("complaints:resolve", args=[foreign_public.pk])
            ).status_code,
            404,
        )

        foreign_pending.refresh_from_db()
        foreign_public.refresh_from_db()
        self.assertEqual(foreign_pending.status, Complaint.Status.PENDING)
        self.assertIsNone(foreign_pending.withdrawn_at)
        self.assertEqual(foreign_public.status, Complaint.Status.PUBLISHED)

    def test_resolve_and_withdraw_serialize_to_valid_terminal_outcomes(self):
        withdrawn_first = self.complaint()
        withdraw_complaint(complaint=withdrawn_first, actor=self.owner)
        with self.assertRaises(ComplaintStateConflict):
            resolve_complaint(
                complaint_id=withdrawn_first.pk,
                actor=self.owner,
            )

        resolved_first = self.complaint()
        resolve_complaint(complaint_id=resolved_first.pk, actor=self.owner)
        with self.assertRaises(ComplaintStateConflict):
            withdraw_complaint(complaint=resolved_first, actor=self.owner)

        withdrawn_first.refresh_from_db()
        resolved_first.refresh_from_db()
        self.assertIsNotNone(withdrawn_first.withdrawn_at)
        self.assertEqual(withdrawn_first.status, Complaint.Status.PUBLISHED)
        self.assertIsNone(resolved_first.withdrawn_at)
        self.assertEqual(resolved_first.status, Complaint.Status.RESOLVED)
        self.assertEqual(
            withdrawn_first.timeline_events.filter(
                event_type=ComplaintEvent.Type.WITHDRAWN,
            ).count(),
            1,
        )
        self.assertEqual(
            resolved_first.timeline_events.filter(
                event_type=ComplaintEvent.Type.RESOLVED,
            ).count(),
            1,
        )

    def test_suspended_user_is_denied_every_complaint_write(self):
        complaint = self.complaint()
        comment = ComplaintComment.objects.create(
            complaint=complaint,
            author_user=self.owner,
            body="Suspended user comment",
        )
        self.client.force_login(self.owner)
        User.objects.filter(pk=self.owner.pk).update(is_suspended=True)

        requests = (
            (reverse("complaints:create"), {}),
            (reverse("complaints:edit", args=[complaint.pk]), {}),
            (reverse("complaints:withdraw", args=[complaint.pk]), {}),
            (reverse("complaints:resolve", args=[complaint.pk]), {}),
            (reverse("complaints:like_toggle", args=[complaint.pk]), {}),
            (
                reverse("complaints:react", args=[complaint.pk]),
                {"reaction_type": "👍"},
            ),
            (
                reverse("complaints:comment_create", args=[complaint.pk]),
                {"body": "Blocked comment"},
            ),
            (
                reverse(
                    "complaints:comment_delete",
                    args=[complaint.pk, comment.pk],
                ),
                {},
            ),
            (
                reverse("complaints:report", args=[complaint.pk]),
                {"reason": ContentReport.Reason.SPAM},
            ),
            (
                reverse(
                    "complaints:comment_report",
                    args=[complaint.pk, comment.pk],
                ),
                {"reason": ContentReport.Reason.SPAM},
            ),
            (
                reverse("complaints:user_report", args=[self.other.pk]),
                {"reason": UserReport.Reason.SPAM},
            ),
        )
        for url, data in requests:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data).status_code, 403)

        complaint.refresh_from_db()
        comment.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.PUBLISHED)
        self.assertIsNone(complaint.withdrawn_at)
        self.assertTrue(comment.is_active)
        self.assertFalse(ComplaintLike.objects.exists())
        self.assertFalse(ContentReport.objects.exists())
        self.assertFalse(UserReport.objects.exists())

    def test_company_and_admin_cannot_use_user_mutation_routes(self):
        complaint = self.complaint()
        comment = ComplaintComment.objects.create(
            complaint=complaint,
            author_user=self.owner,
            body="Role boundary comment",
        )
        routes = (
            reverse("complaints:create"),
            reverse("complaints:edit", args=[complaint.pk]),
            reverse("complaints:withdraw", args=[complaint.pk]),
            reverse("complaints:resolve", args=[complaint.pk]),
            reverse("complaints:like_toggle", args=[complaint.pk]),
            reverse("complaints:react", args=[complaint.pk]),
            reverse("complaints:comment_create", args=[complaint.pk]),
            reverse(
                "complaints:comment_delete",
                args=[complaint.pk, comment.pk],
            ),
            reverse("complaints:report", args=[complaint.pk]),
            reverse(
                "complaints:comment_report",
                args=[complaint.pk, comment.pk],
            ),
            reverse("complaints:user_report", args=[self.other.pk]),
        )

        for actor in (self.company_actor, self.admin):
            self.client.force_login(actor)
            for url in routes:
                with self.subTest(actor=actor.user_type, url=url):
                    self.assertEqual(self.client.post(url).status_code, 403)

        complaint.refresh_from_db()
        comment.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.PUBLISHED)
        self.assertIsNone(complaint.withdrawn_at)
        self.assertTrue(comment.is_active)

    def test_nested_comment_idor_and_cross_author_delete_fail_closed(self):
        first = self.complaint()
        second = self.complaint()
        comment = ComplaintComment.objects.create(
            complaint=second,
            author_user=self.other,
            body="Comment belonging to the second complaint",
        )
        self.client.force_login(self.owner)

        for route in ("comment_delete", "comment_report"):
            response = self.client.post(
                reverse(f"complaints:{route}", args=[first.pk, comment.pk]),
                {"reason": ContentReport.Reason.SPAM},
            )
            self.assertEqual(response.status_code, 404)

        self.assertEqual(
            self.client.post(
                reverse(
                    "complaints:comment_delete",
                    args=[second.pk, comment.pk],
                )
            ).status_code,
            404,
        )
        comment.refresh_from_db()
        self.assertTrue(comment.is_active)
        self.assertFalse(ContentReport.objects.exists())

    def test_duplicate_reports_and_active_restriction_are_fail_safe(self):
        complaint = self.complaint()
        comment = ComplaintComment.objects.create(
            complaint=complaint,
            author_user=self.owner,
            body="Reportable comment",
        )
        self.client.force_login(self.other)

        requests = (
            (
                reverse("complaints:report", args=[complaint.pk]),
                {"reason": ContentReport.Reason.SPAM},
            ),
            (
                reverse(
                    "complaints:comment_report",
                    args=[complaint.pk, comment.pk],
                ),
                {"reason": ContentReport.Reason.HARASSMENT},
            ),
            (
                reverse("complaints:user_report", args=[self.owner.pk]),
                {"reason": UserReport.Reason.SPAM},
            ),
            (
                reverse(
                    "companies_public:company_report",
                    args=[self.company.slug],
                ),
                {"reason": CompanyReport.Reason.MISLEADING},
            ),
        )
        for url, data in requests:
            self.client.post(url, data)
            self.client.post(url, data)

        self.assertEqual(ContentReport.objects.count(), 2)
        self.assertEqual(UserReport.objects.count(), 1)
        self.assertEqual(CompanyReport.objects.count(), 1)

        ReportRestriction.objects.create(
            user=self.other,
            kind=ReportRestriction.Kind.FULL_BLOCK,
            starts_at=timezone.now() - timedelta(minutes=1),
            ends_at=timezone.now() + timedelta(days=1),
        )
        second_complaint = self.complaint()
        second_comment = ComplaintComment.objects.create(
            complaint=second_complaint,
            author_user=self.owner,
            body="Second reportable comment",
        )
        third_user = User.objects.create_user(
            username="hardening-third",
            email="hardening-third@example.com",
            user_type=User.UserType.USER,
        )
        second_company = Company.objects.create(
            name="Second Report Company",
            is_active=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )
        blocked_requests = (
            (
                reverse("complaints:report", args=[second_complaint.pk]),
                {"reason": ContentReport.Reason.SPAM},
            ),
            (
                reverse(
                    "complaints:comment_report",
                    args=[second_complaint.pk, second_comment.pk],
                ),
                {"reason": ContentReport.Reason.SPAM},
            ),
            (
                reverse("complaints:user_report", args=[third_user.pk]),
                {"reason": UserReport.Reason.SPAM},
            ),
            (
                reverse(
                    "companies_public:company_report",
                    args=[second_company.slug],
                ),
                {"reason": CompanyReport.Reason.FRAUD},
            ),
        )
        for url, data in blocked_requests:
            self.client.post(url, data)

        self.assertEqual(ContentReport.objects.count(), 2)
        self.assertEqual(UserReport.objects.count(), 1)
        self.assertEqual(CompanyReport.objects.count(), 1)

    def test_like_uniqueness_is_database_backed(self):
        complaint = self.complaint()
        ComplaintLike.objects.create(complaint=complaint, user=self.other)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ComplaintLike.objects.bulk_create(
                    [ComplaintLike(complaint=complaint, user=self.other)]
                )

    def test_company_service_rechecks_violation_removal_under_complaint_lock(self):
        complaint = self.complaint()
        Complaint.objects.filter(pk=complaint.pk).update(
            violation_removed_at=timezone.now(),
        )

        with self.assertRaises(ValidationError):
            create_company_entry(
                user=self.company_actor,
                company_id=self.company.pk,
                complaint_id=complaint.pk,
                body="This company response must not be created.",
            )

        self.assertFalse(CompanyResponse.objects.filter(complaint=complaint).exists())

    def test_mutations_reject_get_and_require_csrf(self):
        complaint = self.complaint()
        comment = ComplaintComment.objects.create(
            complaint=complaint,
            author_user=self.owner,
            body="CSRF boundary comment",
        )
        post_only = (
            reverse("complaints:withdraw", args=[complaint.pk]),
            reverse("complaints:resolve", args=[complaint.pk]),
            reverse("complaints:like_toggle", args=[complaint.pk]),
            reverse("complaints:react", args=[complaint.pk]),
            reverse("complaints:comment_create", args=[complaint.pk]),
            reverse(
                "complaints:comment_delete",
                args=[complaint.pk, comment.pk],
            ),
            reverse("complaints:report", args=[complaint.pk]),
            reverse(
                "complaints:comment_report",
                args=[complaint.pk, comment.pk],
            ),
            reverse("complaints:user_report", args=[self.other.pk]),
        )
        self.client.force_login(self.owner)
        for url in post_only:
            with self.subTest(method="GET", url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

        self.assertEqual(
            self.client.put(reverse("complaints:edit", args=[complaint.pk])).status_code,
            405,
        )
        self.assertEqual(
            self.client.put(reverse("complaints:create")).status_code,
            405,
        )

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        for url in (
            *post_only,
            reverse("complaints:edit", args=[complaint.pk]),
            reverse("complaints:create"),
        ):
            with self.subTest(method="POST without CSRF", url=url):
                self.assertEqual(csrf_client.post(url).status_code, 403)

    def test_admin_cannot_publish_withdrawn_pending_complaint(self):
        complaint = self.complaint(status=Complaint.Status.PENDING)
        Complaint.objects.filter(pk=complaint.pk).update(withdrawn_at=timezone.now())
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("adminx:complaint_publish", args=[complaint.pk])
        )

        self.assertEqual(response.status_code, 409)
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.PENDING)

    def test_rejection_notifies_owner_but_never_company(self):
        complaint = self.complaint(status=Complaint.Status.PENDING)
        self.client.force_login(self.admin)

        self.client.post(reverse("adminx:complaint_reject", args=[complaint.pk]))

        self.assertFalse(CompanyNotification.objects.filter(complaint=complaint).exists())
        self.assertTrue(
            Notification.objects.filter(
                complaint=complaint,
                recipient_user=self.owner,
                notification_type=Notification.Type.REJECTED,
            ).exists()
        )

    def test_violation_timestamp_fails_closed_across_public_surfaces(self):
        complaint = self.complaint()
        report = ContentReport.objects.create(
            reporter=self.other,
            target_type=ContentReport.TargetType.COMPLAINT,
            complaint=complaint,
            reason=ContentReport.Reason.SPAM,
        )
        notice = Notification.objects.create(
            recipient_user=self.other,
            recipient_role=Notification.Scope.USER,
            content_report=report,
            notification_type=Notification.Type.CONTENT_REPORT,
            title="Content report decision",
            event_key="hardening:hidden-report-link",
        )
        Complaint.objects.filter(pk=complaint.pk).update(
            violation_removed_at=timezone.now()
        )
        complaint.refresh_from_db()

        self.assertFalse(public_complaints().filter(pk=complaint.pk).exists())
        self.assertFalse(company_can_interact_with_complaint(complaint))
        self.assertEqual(public_company_performance(self.company)["total"], 0)
        self.assertEqual(company_badge_facts((self.company.pk,))[self.company.pk]["total"], 0)
        self.assertNotIn(
            "new-contributor",
            {badge.key for badge in resolve_user_badges(self.owner)},
        )
        self.assertEqual(notice.target_url, reverse("notifications:list"))

        home = self.client.get(reverse("core:home"))
        self.assertEqual(home.context["stats"]["published"], 0)
        self.assertEqual(home.context["stats"]["resolved"], 0)
        self.assertNotContains(home, complaint.title)

        company_page = self.client.get(
            reverse("companies_public:company_detail", args=[self.company.slug])
        )
        self.assertEqual(company_page.context["performance"]["total"], 0)
        self.assertNotContains(company_page, complaint.title)

        profile = self.client.get(
            reverse("accounts:public_profile", args=[self.owner.username])
        )
        self.assertEqual(profile.context["complaint_count"], 0)
        self.assertEqual(profile.context["resolved_count"], 0)
        self.assertNotContains(profile, complaint.title)

        self.client.force_login(self.other)
        self.assertEqual(
            self.client.post(
                reverse("complaints:like_toggle", args=[complaint.pk])
            ).status_code,
            404,
        )

    def test_permanently_closed_user_is_not_reportable(self):
        target = User.objects.create_user(
            username="hardening-closed-target",
            email="hardening-closed-target@example.com",
            user_type=User.UserType.USER,
            is_active=True,
            is_permanently_closed=True,
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("complaints:user_report", args=[target.pk]),
            {"reason": UserReport.Reason.SPAM},
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(UserReport.objects.filter(reported_user=target).exists())

    def test_resolved_comment_report_soft_deletes_comment_idempotently(self):
        complaint = self.complaint()
        comment = ComplaintComment.objects.create(
            complaint=complaint,
            author_user=self.owner,
            body="Reported comment",
        )
        report = ContentReport.objects.create(
            reporter=self.other,
            target_type=ContentReport.TargetType.COMMENT,
            comment=comment,
            reason=ContentReport.Reason.HARASSMENT,
        )
        self.client.force_login(self.admin)
        url = reverse("adminx:report_status", args=[report.pk])

        self.assertEqual(
            self.client.post(url, {"status": ContentReport.Status.RESOLVED}).status_code,
            302,
        )
        self.assertEqual(
            self.client.post(url, {"status": ContentReport.Status.RESOLVED}).status_code,
            302,
        )

        comment.refresh_from_db()
        self.assertFalse(comment.is_active)
        self.assertEqual(
            UserViolation.objects.filter(content_report=report).count(),
            1,
        )

    def test_admin_resolve_rolls_back_state_events_and_notices_if_audit_fails(self):
        complaint = self.complaint()
        self.client.force_login(self.admin)

        with patch(
            "adminx.views.record_admin_audit",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse("adminx:complaint_resolve", args=[complaint.pk])
                )

        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.PUBLISHED)
        self.assertFalse(
            complaint.timeline_events.filter(
                event_type=ComplaintEvent.Type.RESOLVED,
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                complaint=complaint,
                notification_type=Notification.Type.RESOLVED,
            ).exists()
        )
        self.assertFalse(
            CompanyNotification.objects.filter(
                complaint=complaint,
                kind=CompanyNotification.Kind.RESOLVED,
            ).exists()
        )

    def test_report_moderation_rolls_back_violation_and_removal_if_audit_fails(self):
        complaint = self.complaint()
        comment = ComplaintComment.objects.create(
            complaint=complaint,
            author_user=self.owner,
            body="Rollback moderation comment",
        )
        report = ContentReport.objects.create(
            reporter=self.other,
            target_type=ContentReport.TargetType.COMMENT,
            comment=comment,
            reason=ContentReport.Reason.HARASSMENT,
        )
        self.client.force_login(self.admin)

        with patch(
            "adminx.views.record_admin_audit",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse("adminx:report_status", args=[report.pk]),
                    {"status": ContentReport.Status.RESOLVED},
                )

        report.refresh_from_db()
        comment.refresh_from_db()
        self.assertEqual(report.status, ContentReport.Status.PENDING)
        self.assertTrue(comment.is_active)
        self.assertFalse(UserViolation.objects.filter(content_report=report).exists())

    def test_report_moderation_is_post_csrf_and_current_admin_only(self):
        complaint = self.complaint()
        content_report = ContentReport.objects.create(
            reporter=self.other,
            target_type=ContentReport.TargetType.COMPLAINT,
            complaint=complaint,
            reason=ContentReport.Reason.SPAM,
        )
        user_report = UserReport.objects.create(
            reporter=self.other,
            reported_user=self.owner,
            reason=UserReport.Reason.SPAM,
        )
        company_report = CompanyReport.objects.create(
            reporter=self.other,
            company=self.company,
            reason=CompanyReport.Reason.MISLEADING,
        )
        self.client.force_login(self.admin)
        urls = (
            reverse("adminx:report_status", args=[content_report.pk]),
            reverse("adminx:user_report_status", args=[user_report.pk]),
            reverse("adminx:company_report_status", args=[company_report.pk]),
        )
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 405)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        for url in urls:
            self.assertEqual(csrf_client.post(url, {"status": "REJECTED"}).status_code, 403)

        stale_admin = User.objects.get(pk=self.admin.pk)
        User.objects.filter(pk=self.admin.pk).update(user_type=User.UserType.USER)
        with transaction.atomic():
            with self.assertRaises(PermissionDenied):
                lock_current_admin(stale_admin)

        self.assertFalse(AdminAuditLog.objects.exists())

    def test_database_rejects_inconsistent_content_report_target(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ContentReport.objects.bulk_create(
                    [
                        ContentReport(
                            reporter=self.owner,
                            target_type=ContentReport.TargetType.COMPLAINT,
                            reason=ContentReport.Reason.SPAM,
                        )
                    ]
                )
