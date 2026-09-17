import json

from django.test import TestCase
from django.urls import reverse


class AssistantA42ButtonOnlyTests(TestCase):
    def test_message_payload_is_rejected(self):
        response = self.client.post(
            reverse("assistant:interact"),
            data=json.dumps(
                {"message": "şikayetlerimi göster"}
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_action_payload_still_works(self):
        response = self.client.post(
            reverse("assistant:interact"),
            data=json.dumps(
                {"action": "ABOUT_DERTDERMAN"}
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_extra_identity_field_is_rejected(self):
        response = self.client.post(
            reverse("assistant:interact"),
            data=json.dumps(
                {
                    "action": "ABOUT_DERTDERMAN",
                    "user_id": 999,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
