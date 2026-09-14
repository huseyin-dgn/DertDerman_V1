from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from companies.models import Company
from notifications.models import EmailDelivery, Notification

from .models import Complaint, ComplaintEvent


User = get_user_model()


@override_settings(RATE_LIMIT_ENABLED=True)
class ComplaintEditRateLimitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="edit-owner",
            email="edit-owner@example.com",
            password="StrongPass2026!",
            user_type=User.UserType.USER,
        )
        cls.other_owner = User.objects.create_user(
            username="other-edit-owner",
            email="other-edit-owner@example.com",
            password="StrongPass2026!",
            user_type=User.UserType.USER,
        )
        cls.admin = User.objects.create_user(
            username="edit-admin",
            email="edit-admin@example.com",
            password="StrongPass2026!",
            user_type=User.UserType.ADMIN,
            is_staff=True,
        )
        cls.company = Company.objects.create(name="Edit Rate Limit Company")

    def setUp(self):
        cache.clear()
        self.complaint = self._create_complaint(self.owner, "Original complaint")
        self.client.force_login(self.owner)

    def _create_complaint(self, owner, title):
        return Complaint.objects.create(
            user=owner,
            company=self.company,
            category=Complaint.Category.OTHER,
            title=title,
            description="This is a sufficiently long original complaint description.",
            status=Complaint.Status.PUBLISHED,
        )

    def _edit(self, complaint, sequence, *, client=None):
        client = client or self.client
        return client.post(
            reverse("complaints:edit", args=[complaint.pk]),
            {
                "company": self.company.pk,
                "category": Complaint.Category.OTHER,
                "title": f"Edited complaint {sequence}",
                "description": (
                    f"This is sufficiently long edited complaint content {sequence}."
                ),
            },
        )

    def _edit_events(self, complaint):
        return ComplaintEvent.objects.filter(
            complaint=complaint,
            event_type=ComplaintEvent.Type.EDITED,
        )

    def _admin_notifications(self, complaint):
        return Notification.objects.filter(
            recipient_user=self.admin,
            recipient_role=Notification.Scope.ADMIN,
            notification_type="MODERATION",
            complaint=complaint,
        )

    def test_owner_single_edit_succeeds_with_event_and_notification(self):
        response = self._edit(self.complaint, 1)

        self.assertEqual(response.status_code, 302)
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.title, "Edited complaint 1")
        self.assertEqual(self.complaint.status, Complaint.Status.PENDING)
        self.assertEqual(self._edit_events(self.complaint).count(), 1)
        self.assertEqual(self._admin_notifications(self.complaint).count(), 1)

    def test_non_owner_cannot_edit_or_consume_owner_complaint_limit(self):
        other_client = Client()
        other_client.force_login(self.other_owner)

        response = self._edit(self.complaint, "idor", client=other_client)

        self.assertEqual(response.status_code, 404)
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.title, "Original complaint")
        self.assertFalse(self._edit_events(self.complaint).exists())
        self.assertFalse(self._admin_notifications(self.complaint).exists())
        self.assertEqual(EmailDelivery.objects.count(), 0)
        self.assertEqual(self._edit(self.complaint, 1).status_code, 302)

    def test_repeated_edits_are_limited_without_rejected_post_side_effects(self):
        for sequence in range(1, 4):
            self.assertEqual(self._edit(self.complaint, sequence).status_code, 302)

        self.complaint.refresh_from_db()
        accepted_title = self.complaint.title
        event_count = self._edit_events(self.complaint).count()
        notification_count = self._admin_notifications(self.complaint).count()
        delivery_count = EmailDelivery.objects.count()

        with patch("notifications.services.send_admins") as send_admins:
            response = self._edit(self.complaint, 4)

        self.assertEqual(response.status_code, 429)
        send_admins.assert_not_called()
        self.assertEqual(response["Retry-After"], "600")
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.title, accepted_title)
        self.assertEqual(self._edit_events(self.complaint).count(), event_count)
        self.assertEqual(
            self._admin_notifications(self.complaint).count(),
            notification_count,
        )
        self.assertEqual(EmailDelivery.objects.count(), delivery_count)

    def test_each_rapid_successful_edit_notifies_admin(self):
        for sequence in range(1, 4):
            self.assertEqual(self._edit(self.complaint, sequence).status_code, 302)

        self.assertEqual(self._edit_events(self.complaint).count(), 3)
        self.assertEqual(self._admin_notifications(self.complaint).count(), 3)
        self.assertEqual(
            self._admin_notifications(self.complaint)
            .values("event_key")
            .distinct()
            .count(),
            3,
        )

    def test_double_submit_creates_an_event_and_notification_per_success(self):
        self.assertEqual(self._edit(self.complaint, "double").status_code, 302)
        self.assertEqual(self._edit(self.complaint, "double").status_code, 302)

        self.assertEqual(self._edit_events(self.complaint).count(), 2)
        self.assertEqual(self._admin_notifications(self.complaint).count(), 2)

    def test_rate_limit_is_isolated_between_users(self):
        for sequence in range(1, 4):
            self.assertEqual(self._edit(self.complaint, sequence).status_code, 302)
        self.assertEqual(self._edit(self.complaint, 4).status_code, 429)

        other_complaint = self._create_complaint(
            self.other_owner,
            "Other owner's complaint",
        )
        other_client = Client()
        other_client.force_login(self.other_owner)
        response = self._edit(other_complaint, 1, client=other_client)

        self.assertEqual(response.status_code, 302)
        other_complaint.refresh_from_db()
        self.assertEqual(other_complaint.title, "Edited complaint 1")

    def test_rate_limit_is_isolated_between_complaints(self):
        for sequence in range(1, 4):
            self.assertEqual(self._edit(self.complaint, sequence).status_code, 302)
        self.assertEqual(self._edit(self.complaint, 4).status_code, 429)

        second_complaint = self._create_complaint(
            self.owner,
            "Owner's second complaint",
        )
        response = self._edit(second_complaint, 1)

        self.assertEqual(response.status_code, 302)
        second_complaint.refresh_from_db()
        self.assertEqual(second_complaint.title, "Edited complaint 1")
