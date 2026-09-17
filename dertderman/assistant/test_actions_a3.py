from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import reverse

from accounts.models import User

from .actions import AssistantAction
from .context import ActorKind, AssistantContext
from .engine import run_action


def _user(*, verified=True):
    return SimpleNamespace(
        is_authenticated=True,
        pk=123,
        user_type=User.UserType.USER,
        is_active=True,
        is_permanently_closed=False,
        is_verified=verified,
    )


class AssistantA3ActionTests(SimpleTestCase):
    def setUp(self):
        self.user_context = AssistantContext(
            kind=ActorKind.USER,
            user=_user(),
            company_memberships=(),
        )
        self.anonymous_context = AssistantContext(
            kind=ActorKind.ANONYMOUS,
            user=None,
            company_memberships=(),
        )
        self.company_context = AssistantContext(
            kind=ActorKind.COMPANY,
            user=SimpleNamespace(
                is_authenticated=True,
                pk=456,
                user_type=User.UserType.COMPANY,
                is_active=True,
                is_permanently_closed=False,
                is_verified=True,
            ),
            company_memberships=(),
        )

    @patch("assistant.actions.get_my_complaint_summary")
    def test_my_complaints_returns_only_private_user_summary(self, selector):
        selector.return_value = {
            "total": 2,
            "status_distribution": [
                {
                    "status": "PENDING",
                    "label": "İnceleniyor",
                    "count": 1,
                },
                {
                    "status": "PUBLISHED",
                    "label": "Yayında",
                    "count": 1,
                },
            ],
            "latest": {
                "id": 9,
                "title": "Test",
                "status": "PUBLISHED",
                "company_name": "Örnek",
                "created_at": None,
            },
        }

        result = run_action(
            context=self.user_context,
            raw_action=AssistantAction.MY_COMPLAINTS.value,
        )

        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.payload["ok"])
        self.assertIn("toplam 2", result.payload["message"])
        self.assertIn("Yayında", result.payload["message"])
        self.assertEqual(
            result.payload["links"][0]["url"],
            reverse("complaints:list"),
        )
        selector.assert_called_once_with(self.user_context.user)

    @patch("assistant.actions.get_my_notification_summary")
    def test_my_notifications_returns_unread_count(self, selector):
        selector.return_value = {"unread_count": 3}

        result = run_action(
            context=self.user_context,
            raw_action=AssistantAction.MY_NOTIFICATIONS.value,
        )

        self.assertEqual(result.status_code, 200)
        self.assertIn("3 okunmamış", result.payload["message"])
        self.assertEqual(
            result.payload["links"][0]["url"],
            reverse("notifications:list"),
        )
        selector.assert_called_once_with(self.user_context.user)

    def test_account_settings_is_read_only_navigation(self):
        result = run_action(
            context=self.user_context,
            raw_action=AssistantAction.ACCOUNT_SETTINGS.value,
        )

        self.assertEqual(result.status_code, 200)

        urls = {item["url"] for item in result.payload["links"]}
        self.assertEqual(
            urls,
            {
                reverse("accounts:profile"),
                reverse("accounts:profile_edit"),
                reverse("accounts:email_change"),
                reverse("accounts:password_change"),
            },
        )

    def test_private_a3_actions_fail_closed_for_anonymous(self):
        for action in (
            AssistantAction.MY_COMPLAINTS,
            AssistantAction.MY_NOTIFICATIONS,
            AssistantAction.ACCOUNT_SETTINGS,
        ):
            with self.subTest(action=action.value):
                result = run_action(
                    context=self.anonymous_context,
                    raw_action=action.value,
                )
                self.assertEqual(result.status_code, 403)
                self.assertFalse(result.payload["ok"])

    def test_private_a3_actions_fail_closed_for_company(self):
        for action in (
            AssistantAction.MY_COMPLAINTS,
            AssistantAction.MY_NOTIFICATIONS,
            AssistantAction.ACCOUNT_SETTINGS,
        ):
            with self.subTest(action=action.value):
                result = run_action(
                    context=self.company_context,
                    raw_action=action.value,
                )
                self.assertEqual(result.status_code, 403)
                self.assertFalse(result.payload["ok"])

    def test_unverified_user_cannot_use_private_a3_actions(self):
        context = AssistantContext(
            kind=ActorKind.USER,
            user=_user(verified=False),
            company_memberships=(),
        )

        result = run_action(
            context=context,
            raw_action=AssistantAction.ACCOUNT_SETTINGS.value,
        )

        self.assertEqual(result.status_code, 403)
        self.assertFalse(result.payload["ok"])

    def test_contact_support_is_public(self):
        result = run_action(
            context=self.anonymous_context,
            raw_action=AssistantAction.CONTACT_SUPPORT.value,
        )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            {item["url"] for item in result.payload["links"]},
            {
                reverse("core:faq"),
                reverse("core:contact"),
            },
        )
