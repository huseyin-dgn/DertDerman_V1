from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings

from accounts.models import User
from companies.models import Company
from complaints.models import Complaint

from .email_policy import notification_email_policy
from .email_service import EmailDeliveryError
from .models import Notification
from .services import send
from .transactional_email import (
    build_notification_target_url,
    deliver_notification_email,
)


@override_settings(
    TRANSACTIONAL_EMAILS_ENABLED=True,
    SITE_BASE_URL="https://dertderman.com",
)
class TransactionalNotificationEmailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="mail-user",
            email="mail-user@example.com",
            password="StrongRiver#9284",
            user_type=User.UserType.USER,
            is_active=True,
            is_verified=True,
        )
        cls.unverified = User.objects.create_user(
            username="unverified-mail-user",
            email="unverified-mail-user@example.com",
            password="StrongRiver#9284",
            user_type=User.UserType.USER,
            is_active=True,
            is_verified=False,
        )
        cls.admin = User.objects.create_user(
            username="mail-admin",
            email="mail-admin@example.com",
            password="StrongRiver#9284",
            user_type=User.UserType.ADMIN,
            is_active=True,
            is_verified=True,
        )
        cls.company = Company.objects.create(
            name="Mail Company",
            is_verified=True,
        )
        cls.complaint = Complaint.objects.create(
            user=cls.user,
            company=cls.company,
            title="Mail bildirim testi",
            description="Transactional email testi için yeterli açıklama metni.",
        )

    def create_notification(
        self,
        *,
        recipient=None,
        scope=Notification.Scope.USER,
        kind=Notification.Type.PUBLISHED,
        event_key="mail-test:1",
        title="Şikayetiniz yayınlandı.",
        message="Şikayetiniz artık yayında.",
        complaint=True,
    ):
        return Notification.objects.create(
            recipient_user=recipient or self.user,
            recipient_role=scope,
            notification_type=kind,
            event_key=event_key,
            title=title,
            message=message,
            complaint=self.complaint if complaint else None,
        )

    def test_published_notification_is_emailed(self):
        notification = self.create_notification()
        decision = notification_email_policy(notification)
        self.assertTrue(decision.should_send)
        self.assertEqual(decision.category_label, "ŞİKAYET GÜNCELLEMESİ")

    def test_company_response_is_emailed(self):
        notification = self.create_notification(
            kind="RESPONSE",
            event_key="response:44",
            title="Şirket şikayetinize cevap verdi.",
        )
        self.assertTrue(notification_email_policy(notification).should_send)

    def test_social_events_are_not_emailed(self):
        for kind in ("LIKE", "REACTION", "COMMENT"):
            with self.subTest(kind=kind):
                notification = self.create_notification(
                    kind=kind,
                    event_key=f"social:{kind}",
                )
                self.assertFalse(
                    notification_email_policy(notification).should_send
                )

    def test_received_and_updated_events_are_not_emailed(self):
        for kind in ("RECEIVED", "UPDATED", "MODERATION"):
            with self.subTest(kind=kind):
                notification = self.create_notification(
                    kind=kind,
                    event_key=f"routine:{kind}",
                )
                self.assertFalse(
                    notification_email_policy(notification).should_send
                )

    def test_admin_notifications_are_not_emailed(self):
        notification = self.create_notification(
            recipient=self.admin,
            scope=Notification.Scope.ADMIN,
            kind=Notification.Type.CONTENT_REPORT,
            event_key="admin-report:1",
            complaint=False,
        )
        self.assertFalse(notification_email_policy(notification).should_send)

    def test_unverified_user_is_not_emailed(self):
        notification = self.create_notification(
            recipient=self.unverified,
            event_key="unverified:1",
            complaint=False,
        )
        self.assertFalse(notification_email_policy(notification).should_send)

    @override_settings(TRANSACTIONAL_EMAILS_ENABLED=False)
    def test_transactional_email_feature_flag_can_disable_policy(self):
        notification = self.create_notification(event_key="disabled:1")
        self.assertFalse(notification_email_policy(notification).should_send)

    def test_absolute_target_uses_site_base_url_and_internal_target(self):
        notification = self.create_notification(event_key="url:1")
        url = build_notification_target_url(notification)
        self.assertTrue(url.startswith("https://dertderman.com/"))
        self.assertIn(f"/{self.complaint.pk}", url)

    @patch("notifications.transactional_email.send_email")
    def test_delivery_uses_central_email_service_html_and_text(self, send_email):
        send_email.return_value = SimpleNamespace(status="sent")
        notification = self.create_notification(event_key="delivery:1")

        deliver_notification_email(notification)

        send_email.assert_called_once()
        kwargs = send_email.call_args.kwargs
        self.assertEqual(kwargs["recipient_email"], self.user.email)
        self.assertIn("Şikayetiniz yayınlandı", kwargs["subject"])
        self.assertIn("https://dertderman.com/", kwargs["html_body"])
        self.assertIn("https://dertderman.com/", kwargs["text_body"])
        self.assertNotIn(self.user.email, kwargs["event_key"])

    @patch("notifications.transactional_email._safe_deliver")
    @patch("notifications.transactional_email.transaction.on_commit")
    def test_send_schedules_email_only_for_new_notification(
        self,
        on_commit,
        safe_deliver,
    ):
        on_commit.side_effect = lambda callback: callback()

        first = send(
            recipient=self.user,
            scope="USER",
            kind=Notification.Type.PUBLISHED,
            event_key="service-idempotency:1",
            title="Şikayetiniz yayınlandı.",
            message="Şikayetiniz yayında.",
            complaint=self.complaint,
            company=self.company,
        )
        second = send(
            recipient=self.user,
            scope="USER",
            kind=Notification.Type.PUBLISHED,
            event_key="service-idempotency:1",
            title="Şikayetiniz yayınlandı.",
            message="Şikayetiniz yayında.",
            complaint=self.complaint,
            company=self.company,
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            Notification.objects.filter(
                recipient_user=self.user,
                event_key="service-idempotency:1",
            ).count(),
            1,
        )
        safe_deliver.assert_called_once_with(first.pk)

    @patch("notifications.transactional_email._safe_deliver")
    @patch("notifications.transactional_email.transaction.on_commit")
    def test_non_email_policy_event_does_not_schedule(
        self,
        on_commit,
        safe_deliver,
    ):
        on_commit.side_effect = lambda callback: callback()

        send(
            recipient=self.user,
            scope="USER",
            kind="LIKE",
            event_key="like:123",
            title="Şikayetiniz beğenildi.",
            complaint=self.complaint,
            company=self.company,
        )

        on_commit.assert_not_called()
        safe_deliver.assert_not_called()

    @patch("notifications.transactional_email.deliver_notification_email")
    def test_provider_failure_is_swallowed_by_safe_boundary(self, deliver):
        from .transactional_email import _safe_deliver

        notification = self.create_notification(event_key="provider-failure:1")
        deliver.side_effect = EmailDeliveryError("provider detail")

        result = _safe_deliver(notification.pk)

        self.assertIsNone(result)
