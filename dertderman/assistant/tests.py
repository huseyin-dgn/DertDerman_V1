import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import (
    Client,
    TestCase,
    override_settings,
)
from django.urls import reverse

from companies.models import (
    Company,
    CompanyMembership,
)
from complaints.models import Complaint
from notifications.models import Notification

from .actions import AssistantAction
from .context import (
    ActorKind,
    resolve_actor_context,
    resolve_company_membership,
)


User = get_user_model()


class AssistantA1Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="assistant-user",
            email="assistant-user@example.com",
            password="StrongPass123!",
            user_type=User.UserType.USER,
            is_verified=True,
        )
        cls.other_user = User.objects.create_user(
            username="assistant-other",
            email="assistant-other@example.com",
            password="StrongPass123!",
            user_type=User.UserType.USER,
            is_verified=True,
        )
        cls.company_user = User.objects.create_user(
            username="assistant-company",
            email="assistant-company@example.com",
            password="StrongPass123!",
            user_type=User.UserType.COMPANY,
        )
        cls.admin = User.objects.create_user(
            username="assistant-admin",
            email="assistant-admin@example.com",
            password="StrongPass123!",
            user_type=User.UserType.ADMIN,
        )
        cls.inactive_user = User.objects.create_user(
            username="assistant-inactive",
            email="assistant-inactive@example.com",
            password="StrongPass123!",
            user_type=User.UserType.USER,
            is_verified=True,
            is_active=False,
        )
        cls.closed_user = User.objects.create_user(
            username="assistant-closed",
            email="assistant-closed@example.com",
            password="StrongPass123!",
            user_type=User.UserType.USER,
            is_verified=True,
            is_permanently_closed=True,
        )
        cls.unverified_user = User.objects.create_user(
            username="assistant-unverified",
            email="assistant-unverified@example.com",
            password="StrongPass123!",
            user_type=User.UserType.USER,
            is_verified=False,
        )
        cls.suspended_user = User.objects.create_user(
            username="assistant-suspended",
            email="assistant-suspended@example.com",
            password="StrongPass123!",
            user_type=User.UserType.USER,
            is_verified=True,
            is_suspended=True,
        )
        cls.invalid_role_user = User.objects.create_user(
            username="assistant-invalid-role",
            email="assistant-invalid-role@example.com",
            password="StrongPass123!",
            user_type="BROKEN",
            is_verified=True,
        )

        cls.company = Company.objects.create(
            name="Assistant Company",
            is_active=True,
            is_verified=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )
        cls.foreign_company = Company.objects.create(
            name="Foreign Assistant Company",
            is_active=True,
            is_verified=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )
        cls.company_membership = CompanyMembership.objects.create(
            user=cls.company_user,
            company=cls.company,
            role=CompanyMembership.Role.OWNER,
            is_active=True,
        )

        cls.own_pending = Complaint.objects.create(
            user=cls.user,
            company=cls.company,
            title="Assistant pending complaint",
            description=(
                "Assistant testi için yeterince uzun "
                "bir şikayet açıklamasıdır."
            ),
            status=Complaint.Status.PENDING,
        )
        cls.own_published = Complaint.objects.create(
            user=cls.user,
            company=cls.company,
            title="Assistant published complaint",
            description=(
                "Assistant testi için ikinci yeterince uzun "
                "şikayet açıklamasıdır."
            ),
            status=Complaint.Status.PUBLISHED,
        )
        cls.other_complaint = Complaint.objects.create(
            user=cls.other_user,
            company=cls.company,
            title="Other user's private complaint",
            description=(
                "Başka kullanıcıya ait yeterince uzun "
                "özel şikayet açıklamasıdır."
            ),
            status=Complaint.Status.PUBLISHED,
        )
        Notification.objects.filter(
        recipient_user=cls.user,
        recipient_role=Notification.Scope.USER,
            ).delete()

        Notification.objects.create(
            recipient_user=cls.user,
            recipient_role=Notification.Scope.USER,
            notification_type=Notification.Type.CREATED,
            title="Assistant unread notification",
            message="Unread",
            event_key="assistant-a1-unread",
            is_read=False,
        )

    def setUp(self):
        cache.clear()
        self.url = reverse(
            "assistant:interact"
        )

    def post_action(
        self,
        action,
        *,
        client=None,
        extra=None,
        remote_addr="127.0.0.1",
    ):
        active_client = client or self.client
        payload = {
            "action": action,
        }
        if extra:
            payload.update(extra)

        return active_client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
            REMOTE_ADDR=remote_addr,
        )

    def test_anonymous_public_action_works(self):
        response = self.post_action(
            AssistantAction.ABOUT_DERTDERMAN.value
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertTrue(
            response.json()["ok"]
        )

    def test_anonymous_private_action_fails_closed(self):
        before_admin_notifications = (
            Notification.objects.filter(
                recipient_role=Notification.Scope.ADMIN
            ).count()
        )

        response = self.post_action(
            AssistantAction.MY_SUMMARY.value
        )

        self.assertEqual(
            response.status_code,
            403,
        )
        self.assertIn(
            "oturum aç",
            response.json()["message"],
        )
        self.assertNotIn(
            "data",
            response.json(),
        )
        self.assertEqual(
            Notification.objects.filter(
                recipient_role=Notification.Scope.ADMIN
            ).count(),
            before_admin_notifications,
        )

    def test_user_gets_only_own_summary(self):
        self.client.force_login(
            self.user
        )

        response = self.post_action(
            AssistantAction.MY_SUMMARY.value
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        data = response.json()["data"]
        self.assertEqual(
            data["complaints"]["total"],
            2,
        )
        self.assertEqual(
            data["notifications"]["unread_count"],
            1,
        )
        self.assertEqual(
            data["complaints"]["latest"]["id"],
            self.own_published.pk,
        )
        self.assertNotIn(
            self.other_complaint.title,
            response.content.decode("utf-8"),
        )

    def test_forged_user_id_is_rejected(self):
        self.client.force_login(
            self.user
        )

        response = self.post_action(
            AssistantAction.MY_SUMMARY.value,
            extra={
                "user_id": self.other_user.pk,
            },
        )

        self.assertEqual(
            response.status_code,
            400,
        )
        self.assertNotIn(
            self.other_complaint.title,
            response.content.decode("utf-8"),
        )

    def test_company_cannot_use_user_private_action(self):
        self.client.force_login(
            self.company_user
        )

        response = self.post_action(
            AssistantAction.MY_SUMMARY.value
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_admin_cannot_use_user_private_action(self):
        self.client.force_login(
            self.admin
        )

        response = self.post_action(
            AssistantAction.MY_SUMMARY.value
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_invalid_role_fails_closed(self):
        self.client.force_login(
            self.invalid_role_user
        )

        private_response = self.post_action(
            AssistantAction.MY_SUMMARY.value
        )
        public_response = self.post_action(
            AssistantAction.ABOUT_DERTDERMAN.value
        )

        self.assertEqual(
            private_response.status_code,
            403,
        )
        self.assertEqual(
            public_response.status_code,
            403,
        )

    def test_inactive_account_private_access_fails_closed(self):
        self.client.force_login(
            self.inactive_user
        )

        response = self.post_action(
            AssistantAction.MY_SUMMARY.value
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_permanently_closed_private_access_fails_closed(self):
        self.client.force_login(
            self.closed_user
        )

        response = self.post_action(
            AssistantAction.MY_SUMMARY.value
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_unverified_user_private_access_fails_closed(self):
        self.client.force_login(
            self.unverified_user
        )

        response = self.post_action(
            AssistantAction.MY_SUMMARY.value
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_suspended_user_read_only_access_is_preserved(self):
        self.client.force_login(
            self.suspended_user
        )

        response = self.post_action(
            AssistantAction.MY_SUMMARY.value
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.json()["data"]["complaints"]["total"],
            0,
        )

    def test_unknown_action_fails_closed(self):
        response = self.post_action(
            "DO_SOMETHING_DYNAMIC"
        )

        self.assertEqual(
            response.status_code,
            400,
        )
        self.assertEqual(
            response.json()["error"],
            "UNKNOWN_ACTION",
        )

    def test_get_is_not_allowed(self):
        response = self.client.get(
            self.url
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_invalid_json_is_rejected(self):
        response = self.client.post(
            self.url,
            data="{not-json",
            content_type="application/json",
        )

        self.assertEqual(
            response.status_code,
            400,
        )

    def test_non_json_request_is_rejected(self):
        response = self.client.post(
            self.url,
            data={
                "action":
                    AssistantAction
                    .ABOUT_DERTDERMAN
                    .value,
            },
        )

        self.assertEqual(
            response.status_code,
            415,
        )

    def test_csrf_is_enforced(self):
        csrf_client = Client(
            enforce_csrf_checks=True
        )
        csrf_client.force_login(
            self.user
        )

        response = csrf_client.post(
            self.url,
            data=json.dumps(
                {
                    "action":
                        AssistantAction
                        .MY_SUMMARY
                        .value,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_private_response_is_not_cacheable(self):
        self.client.force_login(
            self.user
        )

        response = self.post_action(
            AssistantAction.MY_SUMMARY.value
        )

        cache_control = response.headers.get(
            "Cache-Control",
            "",
        ).lower()

        self.assertIn(
            "private",
            cache_control,
        )
        self.assertIn(
            "no-store",
            cache_control,
        )
        self.assertIn(
            "no-cache",
            cache_control,
        )

    def test_read_only_action_does_not_mutate_data(self):
        self.client.force_login(
            self.user
        )

        complaint_snapshot = list(
            Complaint.objects
            .order_by("pk")
            .values_list(
                "pk",
                "status",
                "withdrawn_at",
            )
        )
        notification_snapshot = list(
            Notification.objects
            .order_by("pk")
            .values_list(
                "pk",
                "is_read",
            )
        )

        response = self.post_action(
            AssistantAction.MY_SUMMARY.value
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            list(
                Complaint.objects
                .order_by("pk")
                .values_list(
                    "pk",
                    "status",
                    "withdrawn_at",
                )
            ),
            complaint_snapshot,
        )
        self.assertEqual(
            list(
                Notification.objects
                .order_by("pk")
                .values_list(
                    "pk",
                    "is_read",
                )
            ),
            notification_snapshot,
        )

    def test_company_context_only_resolves_accessible_company(self):
        context = resolve_actor_context(
            self.company_user
        )

        self.assertEqual(
            context.kind,
            ActorKind.COMPANY,
        )

        membership = resolve_company_membership(
            context,
            self.company.pk,
        )
        foreign = resolve_company_membership(
            context,
            self.foreign_company.pk,
        )

        self.assertIsNotNone(
            membership
        )
        self.assertEqual(
            membership.pk,
            self.company_membership.pk,
        )
        self.assertIsNone(
            foreign
        )

    @override_settings(
        RATE_LIMIT_ENABLED=True
    )
    def test_anonymous_rate_limit_uses_existing_backend(self):
        with patch(
            "assistant.views.ANONYMOUS_RATE_LIMIT",
            2,
        ):
            first = self.post_action(
                AssistantAction.ABOUT_DERTDERMAN.value,
                remote_addr="203.0.113.10",
            )
            second = self.post_action(
                AssistantAction.ABOUT_DERTDERMAN.value,
                remote_addr="203.0.113.10",
            )
            third = self.post_action(
                AssistantAction.ABOUT_DERTDERMAN.value,
                remote_addr="203.0.113.10",
            )

        self.assertEqual(
            first.status_code,
            200,
        )
        self.assertEqual(
            second.status_code,
            200,
        )
        self.assertEqual(
            third.status_code,
            429,
        )
        self.assertIn(
            "Retry-After",
            third.headers,
        )

    @override_settings(
        RATE_LIMIT_ENABLED=True
    )
    def test_authenticated_rate_limit_uses_user_identity(self):
        self.client.force_login(
            self.user
        )

        with patch(
            "assistant.views.AUTHENTICATED_RATE_LIMIT",
            2,
        ):
            first = self.post_action(
                AssistantAction.ABOUT_DERTDERMAN.value
            )
            second = self.post_action(
                AssistantAction.ABOUT_DERTDERMAN.value
            )
            third = self.post_action(
                AssistantAction.ABOUT_DERTDERMAN.value
            )

        self.assertEqual(
            first.status_code,
            200,
        )
        self.assertEqual(
            second.status_code,
            200,
        )
        self.assertEqual(
            third.status_code,
            429,
        )
