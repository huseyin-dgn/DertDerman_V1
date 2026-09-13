from django.test import SimpleTestCase
from django.urls import reverse


class ForCompaniesPageTests(SimpleTestCase):

    def test_page_is_public_and_renders_expected_ctas(self):
        response = self.client.get(
            reverse("core:for_companies")
        )

        self.assertEqual(response.status_code, 200)

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

    def test_page_does_not_claim_registration_is_paid(self):
        response = self.client.get(
            reverse("core:for_companies")
        )

        self.assertContains(
            response,
            "Başlamak için ücret ödemeniz gerekmez.",
        )
