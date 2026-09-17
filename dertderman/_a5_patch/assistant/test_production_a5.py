import json

from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse


class AssistantA5ProductionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_public_response_has_security_headers(self):
        response = self.client.post(
            reverse("assistant:interact"),
            data=json.dumps(
                {
                    "action": "ABOUT_DERTDERMAN",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            response["X-Content-Type-Options"],
            "nosniff",
        )

        self.assertEqual(
            response["Referrer-Policy"],
            "same-origin",
        )

        self.assertEqual(
            response["X-Frame-Options"],
            "DENY",
        )

        self.assertIn(
            "Cookie",
            response.get(
                "Vary",
                "",
            ),
        )

    def test_assistant_response_remains_private_no_store(self):
        response = self.client.post(
            reverse("assistant:interact"),
            data=json.dumps(
                {
                    "action": "ABOUT_DERTDERMAN",
                }
            ),
            content_type="application/json",
        )

        cache_control = response.get(
            "Cache-Control",
            "",
        )

        self.assertIn(
            "private",
            cache_control,
        )

        self.assertIn(
            "no-store",
            cache_control,
        )

    def test_widget_has_accessible_dialog_labels(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()

        html = render_to_string(
            "components/assistant_widget.html",
            request=request,
        )

        self.assertIn(
            'role="dialog"',
            html,
        )

        self.assertIn(
            'aria-labelledby="dd-assistant-title"',
            html,
        )

        self.assertIn(
            'aria-describedby="dd-assistant-description"',
            html,
        )

        self.assertNotIn(
            "data-assistant-text-form",
            html,
        )
