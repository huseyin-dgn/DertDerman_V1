from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import Company

from .forms import ComplaintEditForm
from .models import Complaint, ComplaintEvent
from .services import (
    ComplaintStateConflict,
    edit_complaint,
    resolve_complaint,
)


User = get_user_model()


class ComplaintTerminalStateGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="terminal-owner",
            email="terminal-owner@example.com",
            password="StrongPass2026!",
            user_type=User.UserType.USER,
        )

        cls.admin = User.objects.create_user(
            username="terminal-admin",
            email="terminal-admin@example.com",
            password="StrongPass2026!",
            user_type=User.UserType.ADMIN,
            is_staff=True,
        )

        cls.company = Company.objects.create(
            name="Terminal State Company",
        )

    def create_complaint(
        self,
        *,
        status=Complaint.Status.PUBLISHED,
        withdrawn_at=None,
        removed_for_violation=False,
        violation_removed_at=None,
    ):
        return Complaint.objects.create(
            user=self.owner,
            company=self.company,
            category=Complaint.Category.OTHER,
            title="Lifecycle complaint",
            description=(
                "This is a sufficiently long complaint "
                "description for lifecycle security tests."
            ),
            status=status,
            withdrawn_at=withdrawn_at,
            removed_for_violation=removed_for_violation,
            violation_removed_at=violation_removed_at,
        )

    def edit_form(self, complaint):
        form = ComplaintEditForm(
            {
                "company": self.company.pk,
                "category": Complaint.Category.OTHER,
                "title": "Changed lifecycle complaint",
                "description": (
                    "This edited description is sufficiently "
                    "long for the complaint form."
                ),
            },
            instance=complaint,
        )

        self.assertTrue(
            form.is_valid(),
            form.errors,
        )

        return form

    def test_removed_complaint_edit_view_is_blocked(self):
        complaint = self.create_complaint(
            status=Complaint.Status.REMOVED,
            removed_for_violation=True,
            violation_removed_at=timezone.now(),
        )

        self.client.force_login(self.owner)

        response = self.client.get(
            reverse(
                "complaints:edit",
                args=[complaint.pk],
            )
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        response = self.client.post(
            reverse(
                "complaints:edit",
                args=[complaint.pk],
            ),
            {
                "company": self.company.pk,
                "category": Complaint.Category.OTHER,
                "title": "Bypass attempt title",
                "description": (
                    "This bypass attempt must never "
                    "modify moderation evidence."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        complaint.refresh_from_db()

        self.assertEqual(
            complaint.title,
            "Lifecycle complaint",
        )

        self.assertFalse(
            ComplaintEvent.objects.filter(
                complaint=complaint,
                event_type=ComplaintEvent.Type.EDITED,
            ).exists()
        )

    def test_removed_complaint_service_edit_is_blocked(self):
        complaint = self.create_complaint(
            status=Complaint.Status.REMOVED,
        )

        form = self.edit_form(complaint)

        with self.assertRaises(
            ComplaintStateConflict
        ):
            edit_complaint(
                complaint=complaint,
                form=form,
                actor=self.owner,
            )

        complaint.refresh_from_db()

        self.assertEqual(
            complaint.title,
            "Lifecycle complaint",
        )

    def test_violation_flag_blocks_edit_even_if_status_is_published(self):
        complaint = self.create_complaint(
            status=Complaint.Status.PUBLISHED,
            removed_for_violation=True,
            violation_removed_at=timezone.now(),
        )

        form = self.edit_form(complaint)

        with self.assertRaises(
            ComplaintStateConflict
        ):
            edit_complaint(
                complaint=complaint,
                form=form,
                actor=self.owner,
            )

        complaint.refresh_from_db()

        self.assertEqual(
            complaint.status,
            Complaint.Status.PUBLISHED,
        )

        self.assertEqual(
            complaint.title,
            "Lifecycle complaint",
        )

    def test_withdrawn_published_complaint_cannot_be_resolved_by_owner(self):
        complaint = self.create_complaint(
            status=Complaint.Status.PUBLISHED,
            withdrawn_at=timezone.now(),
        )

        with self.assertRaises(
            ComplaintStateConflict
        ):
            resolve_complaint(
                complaint_id=complaint.pk,
                actor=self.owner,
                owner_id=self.owner.pk,
            )

        complaint.refresh_from_db()

        self.assertEqual(
            complaint.status,
            Complaint.Status.PUBLISHED,
        )

        self.assertFalse(
            ComplaintEvent.objects.filter(
                complaint=complaint,
                event_type=ComplaintEvent.Type.RESOLVED,
            ).exists()
        )

    def test_withdrawn_published_complaint_cannot_be_resolved_by_admin(self):
        complaint = self.create_complaint(
            status=Complaint.Status.PUBLISHED,
            withdrawn_at=timezone.now(),
        )

        with self.assertRaises(
            ComplaintStateConflict
        ):
            resolve_complaint(
                complaint_id=complaint.pk,
                actor=self.admin,
            )

        complaint.refresh_from_db()

        self.assertEqual(
            complaint.status,
            Complaint.Status.PUBLISHED,
        )

    def test_resolve_endpoint_does_not_mutate_withdrawn_complaint(self):
        complaint = self.create_complaint(
            status=Complaint.Status.PUBLISHED,
            withdrawn_at=timezone.now(),
        )

        self.client.force_login(
            self.owner
        )

        response = self.client.post(
            reverse(
                "complaints:resolve",
                args=[complaint.pk],
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        complaint.refresh_from_db()

        self.assertEqual(
            complaint.status,
            Complaint.Status.PUBLISHED,
        )

        self.assertFalse(
            ComplaintEvent.objects.filter(
                complaint=complaint,
                event_type=ComplaintEvent.Type.RESOLVED,
            ).exists()
        )
