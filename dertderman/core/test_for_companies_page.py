from django.test import SimpleTestCase
from django.urls import reverse


class ForCompaniesPageTests(SimpleTestCase):

    def test_page_is_public_and_renders_expected_ctas(self):
        response = self.client.get(
            reverse("core:for_companies")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertTemplateUsed(
            response,
            "core/for_companies.html",
        )

        self.assertContains(
            response,
            "Ücretsiz Firma Kaydı",
        )

        self.assertContains(
            response,
            reverse("company_auth:register"),
        )

        self.assertContains(
            response,
            reverse("company_auth:login"),
        )

    def test_page_explains_free_and_pro_plans(self):
        response = self.client.get(
            reverse("core:for_companies")
        )

        self.assertContains(
            response,
            "Firma kaydı ücretsizdir. Ödeme bilgisi gerekmez.",
        )

        self.assertContains(
            response,
            "DertDerman Pro",
        )

        self.assertContains(
            response,
            "₺49,90",
        )

        self.assertContains(
            response,
            "Şikayetlere kurumsal yanıt verme",
        )
