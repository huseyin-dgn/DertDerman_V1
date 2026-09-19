from django.test import SimpleTestCase
from django.urls import reverse

from .advertising_plans import PRO, STANDARD


class AdvertisingPageTests(SimpleTestCase):
    def test_advertising_page_is_public(self):
        response = self.client.get(reverse("core:advertising"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, STANDARD.name)
        self.assertContains(response, PRO.name)

    def test_standard_payment_preview(self):
        response = self.client.get(
            reverse("core:advertising_payment"),
            {"plan": STANDARD.slug},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["plan"], STANDARD)
        self.assertContains(response, "Ödeme altyapısı hazırlanıyor")

    def test_pro_payment_preview(self):
        response = self.client.get(
            reverse("core:advertising_payment"),
            {"plan": PRO.slug},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["plan"], PRO)

    def test_unknown_plan_returns_404(self):
        response = self.client.get(
            reverse("core:advertising_payment"),
            {"plan": "unknown"},
        )

        self.assertEqual(response.status_code, 404)

    def test_query_string_price_cannot_override_server_price(self):
        response = self.client.get(
            reverse("core:advertising_payment"),
            {
                "plan": STANDARD.slug,
                "price": "999999",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["plan"].price_tl,
            STANDARD.price_tl,
        )
        self.assertContains(
            response,
            f"{STANDARD.price_tl} TL",
        )
        self.assertNotContains(response, "999999 TL")
