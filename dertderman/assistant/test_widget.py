from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase

from accounts.models import User


class AssistantWidgetTemplateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.verified_user = User.objects.create_user(
            username="assistant-widget-user",
            email="assistant-widget-user@example.com",
            password="StrongPass123!",
            user_type=User.UserType.USER,
            is_verified=True,
        )
        cls.unverified_user = User.objects.create_user(
            username="assistant-widget-unverified",
            email="assistant-widget-unverified@example.com",
            password="StrongPass123!",
            user_type=User.UserType.USER,
            is_verified=False,
        )
        cls.company_user = User.objects.create_user(
            username="assistant-widget-company",
            email="assistant-widget-company@example.com",
            password="StrongPass123!",
            user_type=User.UserType.COMPANY,
            is_verified=True,
        )

    def setUp(self):
        self.factory = RequestFactory()

    def _render(self, user):
        request = self.factory.get("/")
        request.user = user
        return render_to_string(
            "components/assistant_widget.html",
            request=request,
        )

    def test_anonymous_sees_public_actions_but_not_private_actions(self):
        html = self._render(AnonymousUser())

        self.assertIn('data-assistant-action="ABOUT_DERTDERMAN"', html)
        self.assertIn('data-assistant-action="HOW_TO_REGISTER"', html)
        self.assertIn('data-assistant-action="HOW_TO_LOGIN"', html)
        self.assertNotIn('data-assistant-action="MY_SUMMARY"', html)
        self.assertNotIn('data-assistant-action="MY_COMPLAINTS"', html)

    def test_verified_user_sees_private_action_cards(self):
        html = self._render(self.verified_user)

        self.assertIn('data-assistant-action="MY_SUMMARY"', html)
        self.assertIn('data-assistant-action="MY_COMPLAINTS"', html)
        self.assertIn('data-assistant-action="MY_NOTIFICATIONS"', html)
        self.assertIn('data-assistant-action="ACCOUNT_SETTINGS"', html)
        self.assertNotIn('data-assistant-action="HOW_TO_LOGIN"', html)
        self.assertNotIn('data-assistant-action="HOW_TO_REGISTER"', html)

    def test_unverified_user_does_not_see_private_actions(self):
        html = self._render(self.unverified_user)

        self.assertNotIn('data-assistant-action="MY_SUMMARY"', html)
        self.assertNotIn('data-assistant-action="MY_COMPLAINTS"', html)
        self.assertIn('data-assistant-action="ABOUT_DERTDERMAN"', html)

    def test_widget_has_no_free_text_composer(self):
        html = self._render(self.verified_user)

        self.assertNotIn("data-assistant-text-form", html)
        self.assertNotIn("data-assistant-input", html)
        self.assertNotIn("Asistana yaz", html)

    def test_company_template_has_no_user_private_actions(self):
        html = self._render(self.company_user)

        self.assertNotIn('data-assistant-action="MY_SUMMARY"', html)
        self.assertNotIn('data-assistant-action="MY_COMPLAINTS"', html)
