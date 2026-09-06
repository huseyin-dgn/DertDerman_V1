from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Company, CompanyMembership


User = get_user_model()


class PublicCompanyCtaTests(TestCase):
    def test_anonymous_navbar_company_page_and_footer_expose_company_routes(self):
        home = self.client.get(reverse("core:home"))
        companies = self.client.get(reverse("companies_public:company_list"))

        self.assertContains(home, "Kurumsal")
        self.assertContains(home, f'href="{reverse("company_auth:login")}"')
        self.assertContains(home, f'href="{reverse("company_auth:register")}"')
        self.assertContains(home, "Şirketler için DertDerman")
        self.assertContains(companies, "Şirketiniz de DertDerman’da yerini alsın.")
        self.assertContains(companies, "Şirket Ağına Katıl")
        self.assertContains(companies, "Şirket Girişi")
        self.assertContains(companies, f'href="{reverse("company_auth:register")}"')
        self.assertContains(companies, f'href="{reverse("company_auth:login")}"')

    def test_company_navbar_and_company_cta_point_to_company_panel(self):
        user = User.objects.create_user(
            username="cta-company",
            email="cta-company@example.com",
            password="StrongPass2026!",
            user_type=User.UserType.COMPANY,
        )
        company = Company.objects.create(name="CTA Company")
        CompanyMembership.objects.create(user=user, company=company, is_active=True)
        self.client.force_login(user)

        response = self.client.get(reverse("companies_public:company_list"))

        self.assertContains(response, "Şirket Paneli")
        self.assertContains(response, f'href="{reverse("companies:company_panel")}"')
        self.assertNotContains(response, f'href="{reverse("company_auth:register")}"')
        self.assertNotContains(response, f'href="{reverse("company_auth:login")}"')

    def test_regular_user_sees_company_links_without_company_privilege(self):
        user = User.objects.create_user(
            username="cta-user",
            email="cta-user@example.com",
            password="StrongPass2026!",
            user_type=User.UserType.USER,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("core:home"))

        self.assertContains(response, f'href="{reverse("company_auth:login")}"')
        self.assertContains(response, f'href="{reverse("company_auth:register")}"')
        self.assertNotContains(response, f'href="{reverse("companies:company_panel")}"')
        self.assertEqual(self.client.get(reverse("companies:company_panel")).status_code, 403)

    def test_admin_does_not_receive_company_registration_cta(self):
        admin = User.objects.create_user(
            username="cta-admin",
            email="cta-admin@example.com",
            password="StrongPass2026!",
            user_type=User.UserType.ADMIN,
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("companies_public:company_list"))

        self.assertContains(response, "Yönetim Paneli")
        self.assertNotContains(response, f'href="{reverse("company_auth:register")}"')
