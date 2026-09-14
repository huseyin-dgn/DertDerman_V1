from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from adminx.models import AdminAuditLog
from notifications.models import Notification

from .models import (
    Company,
    CompanyCategory,
    CompanyMembership,
    CompanyNotification,
    CompanySubscription,
)
from .services import decide_company_application


User = get_user_model()


class CompanyApplicationRejectionTests(TestCase):
    password = "StrongCompanyPass2026!"
    rejection_reason = "Vergi kimliği ile şirket bilgileri doğrulanamadı."

    def setUp(self):
        self.admin = User.objects.create_user(
            username="rejection-admin",
            email="rejection-admin@example.com",
            password=self.password,
            user_type=User.UserType.ADMIN,
        )
        self.owner = User.objects.create_user(
            username="rejection-owner",
            email="rejection-owner@example.com",
            password=self.password,
            user_type=User.UserType.COMPANY,
            phone="05550000000",
        )
        self.category = CompanyCategory.objects.create(
            name="Rejection Test Category",
        )
        self.company = Company.objects.create(
            name="Rejection Test Company",
            email=self.owner.email,
            phone=self.owner.phone,
            website="https://example.com",
            category=self.category,
            approval_status=Company.ApprovalStatus.PENDING,
            is_active=False,
            is_verified=False,
        )
        self.membership = CompanyMembership.objects.create(
            user=self.owner,
            company=self.company,
            role=CompanyMembership.Role.OWNER,
            is_active=False,
        )
        self.decision_url = reverse(
            "adminx:company_application_detail",
            args=[self.company.pk],
        )

    def reject(self, reason=None):
        self.client.force_login(self.admin)
        return self.client.post(
            self.decision_url,
            {
                "action": "reject",
                "rejection_reason": (
                    self.rejection_reason if reason is None else reason
                ),
            },
        )

    def reapplication_data(self, *, password=None):
        return {
            "company_name": "Corrected Rejection Test Company",
            "category": str(self.category.pk),
            "email": self.owner.email,
            "phone": "05551112233",
            "website": "https://corrected.example.com",
            "password": self.password if password is None else password,
        }

    def test_rejection_reason_is_required_in_form_and_service(self):
        response = self.reject("   ")

        self.assertEqual(response.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(
            self.company.approval_status,
            Company.ApprovalStatus.PENDING,
        )
        self.assertEqual(self.company.rejection_reason, "")
        self.assertIsNone(self.company.rejected_at)
        self.assertContains(response, "neden belirtilmelidir")

        with self.assertRaises(ValidationError):
            decide_company_application(
                self.company.pk,
                Company.ApprovalStatus.REJECTED,
                actor=self.admin,
                rejection_reason="\t",
            )

    def test_reject_requires_an_active_authenticated_admin_actor(self):
        Company.objects.filter(pk=self.company.pk).update(
            is_active=True,
            is_verified=True,
        )
        self.membership.is_active = True
        self.membership.save(update_fields=["is_active"])
        inactive_admin = User.objects.create_user(
            username="inactive-rejection-admin",
            email="inactive-rejection-admin@example.com",
            password=self.password,
            user_type=User.UserType.ADMIN,
            is_active=False,
        )

        for actor in (None, self.owner, inactive_admin):
            with self.subTest(actor=actor):
                with self.assertRaises(ValidationError):
                    decide_company_application(
                        self.company.pk,
                        Company.ApprovalStatus.REJECTED,
                        actor=actor,
                        rejection_reason=self.rejection_reason,
                    )

                self.company.refresh_from_db()
                self.membership.refresh_from_db()
                self.assertEqual(
                    self.company.approval_status,
                    Company.ApprovalStatus.PENDING,
                )
                self.assertTrue(self.company.is_active)
                self.assertTrue(self.company.is_verified)
                self.assertTrue(self.membership.is_active)
                self.assertEqual(self.company.rejection_reason, "")
                self.assertIsNone(self.company.rejected_at)
                self.assertFalse(
                    AdminAuditLog.objects.filter(
                        target_type="company_application",
                        target_id=str(self.company.pk),
                    ).exists()
                )

    def test_reject_atomically_closes_access_records_state_and_audit(self):
        Company.objects.filter(pk=self.company.pk).update(
            is_active=True,
            is_verified=True,
        )
        self.membership.is_active = True
        self.membership.save(update_fields=["is_active"])

        response = self.reject(f"  {self.rejection_reason}  ")

        self.assertEqual(response.status_code, 302)
        self.company.refresh_from_db()
        self.membership.refresh_from_db()
        self.assertEqual(
            self.company.approval_status,
            Company.ApprovalStatus.REJECTED,
        )
        self.assertFalse(self.company.is_active)
        self.assertFalse(self.company.is_verified)
        self.assertFalse(self.membership.is_active)
        self.assertEqual(self.company.rejection_reason, self.rejection_reason)
        self.assertIsNotNone(self.company.rejected_at)
        self.assertFalse(
            CompanyNotification.objects.filter(company=self.company).exists()
        )

        audit = AdminAuditLog.objects.get(
            target_type="company_application",
            target_id=str(self.company.pk),
            action=AdminAuditLog.Action.REJECT,
        )
        self.assertEqual(audit.actor, self.admin)
        self.assertEqual(
            audit.metadata["rejection_reason"],
            self.rejection_reason,
        )

        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(reverse("companies:company_panel")).status_code,
            403,
        )

    def test_duplicate_reject_is_noop(self):
        self.assertEqual(self.reject().status_code, 302)
        self.company.refresh_from_db()
        rejected_at = self.company.rejected_at

        response = self.reject("Farklı bir tekrar nedeni")

        self.assertEqual(response.status_code, 409)
        self.company.refresh_from_db()
        self.assertEqual(self.company.rejection_reason, self.rejection_reason)
        self.assertEqual(self.company.rejected_at, rejected_at)
        self.assertEqual(
            AdminAuditLog.objects.filter(
                target_type="company_application",
                target_id=str(self.company.pk),
                action=AdminAuditLog.Action.REJECT,
            ).count(),
            1,
        )
        self.assertFalse(
            CompanyNotification.objects.filter(company=self.company).exists()
        )

    def test_approval_still_creates_panel_notification(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            self.decision_url,
            {"action": "approve", "rejection_reason": ""},
        )

        self.assertEqual(response.status_code, 302)
        notice = CompanyNotification.objects.get(company=self.company)
        self.assertIn("onaylandı", notice.title)
        self.company.refresh_from_db()
        self.membership.refresh_from_db()
        self.assertTrue(self.company.is_active)
        self.assertTrue(self.company.is_verified)
        self.assertTrue(self.membership.is_active)

        self.client.force_login(self.owner)
        inbox = self.client.get(reverse("companies:notifications"))
        self.assertEqual(inbox.status_code, 200)
        self.assertContains(inbox, notice.title)

    def test_reapplication_preserves_reason_records_and_pro_entitlement(self):
        subscription = CompanySubscription.objects.create(
            company=self.company,
            plan=CompanySubscription.Plan.PRO,
            billing_period=CompanySubscription.BillingPeriod.MONTHLY,
            is_active=True,
        )
        self.assertEqual(self.reject().status_code, 302)
        self.company.refresh_from_db()
        rejected_at = self.company.rejected_at
        user_count = User.objects.count()
        company_count = Company.objects.count()
        membership_count = CompanyMembership.objects.count()
        application_notification_count = Notification.objects.filter(
            recipient_user=self.admin,
            recipient_role=Notification.Scope.ADMIN,
            notification_type="APPLICATION",
            company=self.company,
        ).count()
        subscription_state = (
            subscription.pk,
            subscription.plan,
            subscription.is_active,
        )
        self.client.logout()

        invalid = self.client.post(
            reverse("company_auth:reapply"),
            self.reapplication_data(password="WrongPassword2026!"),
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertNotContains(invalid, self.rejection_reason)
        self.company.refresh_from_db()
        self.assertEqual(
            self.company.approval_status,
            Company.ApprovalStatus.REJECTED,
        )

        response = self.client.post(
            reverse("company_auth:reapply"),
            self.reapplication_data(),
        )
        self.assertEqual(response.status_code, 302)
        status_page = self.client.get(reverse("company_auth:login"))
        self.assertNotContains(status_page, self.rejection_reason)
        self.assertEqual(
            Notification.objects.filter(
                recipient_user=self.admin,
                recipient_role=Notification.Scope.ADMIN,
                notification_type="APPLICATION",
                company=self.company,
            ).count(),
            application_notification_count + 1,
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient_user=self.admin,
                recipient_role=Notification.Scope.ADMIN,
                company=self.company,
                title="Şirket başvurusu yeniden inceleme bekliyor.",
            ).exists()
        )
        self.company.refresh_from_db()
        self.membership.refresh_from_db()
        subscription.refresh_from_db()
        self.assertEqual(
            self.company.approval_status,
            Company.ApprovalStatus.PENDING,
        )
        self.assertFalse(self.company.is_active)
        self.assertFalse(self.company.is_verified)
        self.assertFalse(self.membership.is_active)
        self.assertEqual(self.company.rejection_reason, self.rejection_reason)
        self.assertEqual(self.company.rejected_at, rejected_at)
        self.assertEqual(User.objects.count(), user_count)
        self.assertEqual(Company.objects.count(), company_count)
        self.assertEqual(CompanyMembership.objects.count(), membership_count)
        self.assertEqual(
            (subscription.pk, subscription.plan, subscription.is_active),
            subscription_state,
        )
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(reverse("companies:company_panel")).status_code,
            403,
        )
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.post(
                self.decision_url,
                {"action": "approve", "rejection_reason": ""},
            ).status_code,
            302,
        )
        self.assertEqual(
            CompanyNotification.objects.filter(company=self.company).count(),
            1,
        )
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(reverse("companies:company_panel")).status_code,
            200,
        )

    def test_audit_failure_rolls_back_rejection(self):
        Company.objects.filter(pk=self.company.pk).update(
            is_active=True,
            is_verified=True,
        )
        self.membership.is_active = True
        self.membership.save(update_fields=["is_active"])

        with patch(
            "adminx.models.AdminAuditLog.objects.create",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                decide_company_application(
                    self.company.pk,
                    Company.ApprovalStatus.REJECTED,
                    actor=self.admin,
                    rejection_reason=self.rejection_reason,
                )

        self.company.refresh_from_db()
        self.membership.refresh_from_db()
        self.assertEqual(
            self.company.approval_status,
            Company.ApprovalStatus.PENDING,
        )
        self.assertTrue(self.company.is_active)
        self.assertTrue(self.company.is_verified)
        self.assertTrue(self.membership.is_active)
        self.assertEqual(self.company.rejection_reason, "")
        self.assertIsNone(self.company.rejected_at)
