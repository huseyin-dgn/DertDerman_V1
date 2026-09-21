from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from adminx.models import AdminAuditLog
from adminx.services import archive_company

from .forms import COMPANY_REGISTRATION_ERROR, CompanyRegistrationForm
from complaints.models import Complaint

from .models import (
    Company,
    CompanyCategory,
    CompanyMembership,
    CompanyNotification,
    CompanyNotificationRead,
    CompanyResponse,
    InternalCompanyNote,
)
from .panel_permissions import COMPANY_SESSION_KEY
from .services import decide_company_application, resubmit_company_application


PASSWORD = "CompanyHardening2026!"


class CompanyRegistrationRaceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.category = CompanyCategory.objects.create(name="Race Category")

    def registration_data(self):
        return {
            "company_name": "Race Company",
            "category": self.category.pk,
            "first_name": "Race",
            "last_name": "Owner",
            "email": "company-race@example.com",
            "phone": "05551234567",
            "website": "https://example.com",
            "password1": PASSWORD,
            "password2": PASSWORD,
            "terms_accepted": "on",
            "privacy_notice_acknowledged": "on",
        }

    def test_case_variant_registration_race_fails_without_partial_records(self):
        original_save = CompanyRegistrationForm.save

        def create_competing_account(form, commit=True):
            User.objects.create_user(
                username="registration-race-winner",
                email=form.cleaned_data["email"].upper(),
                password=PASSWORD,
            )
            return original_save(form, commit=commit)

        with patch.object(
            CompanyRegistrationForm,
            "save",
            new=create_competing_account,
        ):
            response = self.client.post(
                reverse("company_auth:register"),
                self.registration_data(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, COMPANY_REGISTRATION_ERROR)
        self.assertEqual(
            User.objects.filter(email__iexact="company-race@example.com").count(),
            1,
        )
        self.assertFalse(Company.objects.exists())
        self.assertFalse(CompanyMembership.objects.exists())


class CompanyLifecycleServiceHardeningTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="company-hardening-admin",
            email="company-hardening-admin@example.com",
            password=PASSWORD,
            user_type=User.UserType.ADMIN,
        )
        self.owner = User.objects.create_user(
            username="company-hardening-owner",
            email="company-hardening-owner@example.com",
            password=PASSWORD,
            user_type=User.UserType.COMPANY,
        )
        self.category = CompanyCategory.objects.create(name="Lifecycle Category")
        self.company = Company.objects.create(
            name="Lifecycle Company",
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

    def assert_pending_and_inaccessible(self):
        self.company.refresh_from_db()
        self.membership.refresh_from_db()
        self.assertEqual(
            self.company.approval_status,
            Company.ApprovalStatus.PENDING,
        )
        self.assertFalse(self.company.is_active)
        self.assertFalse(self.company.is_verified)
        self.assertFalse(self.membership.is_active)

    def test_approval_requires_database_current_admin_actor(self):
        inactive_admin = User.objects.create_user(
            username="inactive-company-admin",
            email="inactive-company-admin@example.com",
            user_type=User.UserType.ADMIN,
            is_active=True,
        )
        User.objects.filter(pk=inactive_admin.pk).update(is_active=False)

        for actor in (None, self.owner, inactive_admin):
            with self.subTest(actor=actor):
                with self.assertRaises(ValidationError):
                    decide_company_application(
                        self.company.pk,
                        Company.ApprovalStatus.APPROVED,
                        actor=actor,
                    )
                self.assert_pending_and_inaccessible()

    def test_approval_does_not_reactivate_an_inactive_owner_account(self):
        User.objects.filter(pk=self.owner.pk).update(is_active=False)

        with self.assertRaises(ValidationError):
            decide_company_application(
                self.company.pk,
                Company.ApprovalStatus.APPROVED,
                actor=self.admin,
            )

        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_active)
        self.assert_pending_and_inaccessible()

    def test_approval_audit_failure_rolls_back_the_whole_decision(self):
        with patch(
            "adminx.models.AdminAuditLog.objects.create",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                decide_company_application(
                    self.company.pk,
                    Company.ApprovalStatus.APPROVED,
                    actor=self.admin,
                )

        self.assert_pending_and_inaccessible()

    def test_approval_records_a_durable_admin_audit(self):
        company, changed = decide_company_application(
            self.company.pk,
            Company.ApprovalStatus.APPROVED,
            actor=self.admin,
        )

        self.assertTrue(changed)
        self.assertEqual(company.approval_status, Company.ApprovalStatus.APPROVED)
        audit = AdminAuditLog.objects.get(
            action=AdminAuditLog.Action.PUBLISH,
            target_type="company_application",
            target_id=str(self.company.pk),
        )
        self.assertEqual(audit.actor, self.admin)
        self.assertEqual(
            audit.metadata,
            {
                "previous_status": Company.ApprovalStatus.PENDING,
                "new_status": Company.ApprovalStatus.APPROVED,
            },
        )

    def test_reapplication_service_rechecks_current_owner_account_state(self):
        Company.objects.filter(pk=self.company.pk).update(
            approval_status=Company.ApprovalStatus.REJECTED,
        )
        User.objects.filter(pk=self.owner.pk).update(is_active=False)

        with self.assertRaises(ValidationError):
            resubmit_company_application(
                user=self.owner,
                company_id=self.company.pk,
                company_name="Injected Reapplication",
                category=self.category,
                phone="05550000000",
                website="https://example.com",
            )

        self.company.refresh_from_db()
        self.assertEqual(
            self.company.approval_status,
            Company.ApprovalStatus.REJECTED,
        )
        self.assertEqual(self.company.name, "Lifecycle Company")

    def test_archive_requires_current_admin_and_records_durable_audit(self):
        self.company.approval_status = Company.ApprovalStatus.APPROVED
        self.company.is_active = True
        self.company.is_verified = True
        self.company.save(
            update_fields=["approval_status", "is_active", "is_verified"]
        )

        with self.assertRaises(ValidationError):
            archive_company(pk=self.company.pk, actor=self.owner)
        self.company.refresh_from_db()
        self.assertIsNone(self.company.archived_at)
        self.assertTrue(self.company.is_active)

        self.assertTrue(archive_company(pk=self.company.pk, actor=self.admin))
        self.company.refresh_from_db()
        self.assertIsNotNone(self.company.archived_at)
        self.assertFalse(self.company.is_active)
        audit = AdminAuditLog.objects.get(
            action=AdminAuditLog.Action.ARCHIVE,
            target_type="company",
            target_id=str(self.company.pk),
        )
        self.assertEqual(audit.actor, self.admin)
        self.assertEqual(audit.target_label, self.company.name)

    def test_archive_audit_failure_rolls_back_state_and_notification(self):
        self.company.approval_status = Company.ApprovalStatus.APPROVED
        self.company.is_active = True
        self.company.is_verified = True
        self.company.save(
            update_fields=["approval_status", "is_active", "is_verified"]
        )

        with patch(
            "adminx.services.AdminAuditLog.objects.create",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                archive_company(pk=self.company.pk, actor=self.admin)

        self.company.refresh_from_db()
        self.assertIsNone(self.company.archived_at)
        self.assertTrue(self.company.is_active)
        self.assertFalse(
            CompanyNotification.objects.filter(
                company=self.company,
                title="Şirket arşivlendi.",
            ).exists()
        )


class CompanyPanelAuthorizationHardeningTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="panel-hardening-owner",
            email="panel-hardening-owner@example.com",
            password=PASSWORD,
            user_type=User.UserType.COMPANY,
        )
        cls.support = User.objects.create_user(
            username="panel-hardening-support",
            email="panel-hardening-support@example.com",
            password=PASSWORD,
            user_type=User.UserType.COMPANY,
        )
        cls.consumer = User.objects.create_user(
            username="panel-hardening-consumer",
            email="panel-hardening-consumer@example.com",
            password=PASSWORD,
            user_type=User.UserType.USER,
            is_verified=True,
        )
        cls.company = Company.objects.create(
            name="Authorized Panel Company",
            description="Original description",
            approval_status=Company.ApprovalStatus.APPROVED,
            is_active=True,
            is_verified=True,
        )
        cls.foreign_company = Company.objects.create(
            name="Foreign Panel Company",
            approval_status=Company.ApprovalStatus.APPROVED,
            is_active=True,
            is_verified=True,
        )
        cls.membership = CompanyMembership.objects.create(
            user=cls.owner,
            company=cls.company,
            role=CompanyMembership.Role.OWNER,
            is_active=True,
        )
        cls.support_membership = CompanyMembership.objects.create(
            user=cls.support,
            company=cls.company,
            role=CompanyMembership.Role.SUPPORT,
            is_active=True,
        )
        cls.own_complaint = Complaint.objects.create(
            user=cls.consumer,
            company=cls.company,
            title="Authorized complaint",
            description="Authorized complaint details.",
            status=Complaint.Status.PUBLISHED,
        )
        cls.foreign_complaint = Complaint.objects.create(
            user=cls.consumer,
            company=cls.foreign_company,
            title="Foreign complaint",
            description="Foreign complaint details.",
            status=Complaint.Status.PUBLISHED,
        )
        cls.notification = CompanyNotification.objects.create(
            company=cls.company,
            complaint=cls.own_complaint,
            kind=CompanyNotification.Kind.NEW,
            title="Authorized notification",
        )
        cls.foreign_notification = CompanyNotification.objects.create(
            company=cls.foreign_company,
            complaint=cls.foreign_complaint,
            kind=CompanyNotification.Kind.NEW,
            title="Foreign notification",
        )

    def setUp(self):
        self.client.force_login(self.owner)

    def test_stale_session_rechecks_membership_and_company_state(self):
        cases = (
            (CompanyMembership, self.membership.pk, {"is_active": False}),
            (
                Company,
                self.company.pk,
                {"approval_status": Company.ApprovalStatus.REJECTED},
            ),
            (Company, self.company.pk, {"is_active": False}),
            (Company, self.company.pk, {"archived_at": timezone.now()}),
        )

        for model, pk, changes in cases:
            with self.subTest(model=model.__name__, changes=changes):
                original = model.objects.values().get(pk=pk)
                model.objects.filter(pk=pk).update(**changes)
                try:
                    response = self.client.get(reverse("companies:company_panel"))
                    self.assertEqual(response.status_code, 403)
                    self.assertIn("_auth_user_id", self.client.session)
                finally:
                    model.objects.filter(pk=pk).update(
                        **{field: original[field] for field in changes}
                    )

    def test_tampered_selection_and_switch_never_grant_foreign_access(self):
        session = self.client.session
        session[COMPANY_SESSION_KEY] = self.foreign_company.pk
        session.save()

        dashboard = self.client.get(reverse("companies:company_panel"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.context["company"], self.company)

        switch = self.client.post(
            reverse("companies:switch_company"),
            {"company_id": self.foreign_company.pk},
        )
        self.assertEqual(switch.status_code, 404)

    def test_cross_company_complaint_and_notification_ids_are_404(self):
        detail = reverse(
            "companies:complaint_detail",
            args=[self.foreign_complaint.pk],
        )
        self.assertEqual(self.client.get(detail).status_code, 404)
        for route in ("response_create", "note_create"):
            response = self.client.post(
                reverse(f"companies:{route}", args=[self.foreign_complaint.pk]),
                {"body": "Cross-company content"},
            )
            self.assertEqual(response.status_code, 404)

        read = self.client.post(
            reverse(
                "companies:notification_read",
                args=[self.foreign_notification.pk],
            )
        )
        self.assertEqual(read.status_code, 404)
        self.assertFalse(CompanyResponse.objects.exists())
        self.assertFalse(InternalCompanyNote.objects.exists())
        self.assertFalse(CompanyNotificationRead.objects.exists())

    def test_support_cannot_mutate_profile_or_target_another_company(self):
        client = Client()
        client.force_login(self.support)
        response = client.post(
            reverse("companies:profile"),
            {
                "description": "Unauthorized change",
                "company_id": self.foreign_company.pk,
                "approval_status": Company.ApprovalStatus.REJECTED,
                "is_active": "false",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.company.refresh_from_db()
        self.foreign_company.refresh_from_db()
        self.assertEqual(self.company.description, "Original description")
        self.assertTrue(self.foreign_company.is_active)
