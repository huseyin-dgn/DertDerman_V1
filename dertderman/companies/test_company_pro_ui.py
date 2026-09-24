from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from companies.models import (
    Company,
    CompanyCategory,
    CompanyMembership,
)


User = get_user_model()


class CompanyProPanelUITests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="pro-ui-company",
            email="pro-ui@example.com",
            password="StrongPass2026!",
            user_type=User.UserType.COMPANY,
            is_verified=True,
        )

        category = CompanyCategory.objects.create(
            name="Pro UI Test Category",
        )

        self.company = Company.objects.create(
            name="Pro UI Test Company",
            category=category,
            is_active=True,
            is_verified=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )

        CompanyMembership.objects.create(
            user=self.user,
            company=self.company,
            role=CompanyMembership.Role.OWNER,
            is_active=True,
        )

        self.client.force_login(
            self.user
        )

    def test_plan_page_is_available_to_company_user(self):
        response = self.client.get(
            reverse("companies:plan")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertTemplateUsed(
            response,
            "companies/panel/plan.html",
        )

        self.assertContains(
            response,
            "Standart Firma",
        )

        self.assertContains(
            response,
            "DertDerman Pro",
        )

        self.assertContains(
            response,
            "\u20ba49,90",
        )

        self.assertContains(
            response,
            "\u20ba499,90",
        )

    def test_plan_page_explains_company_response_is_pro(self):
        response = self.client.get(
            reverse("companies:plan")
        )

        self.assertContains(
            response,
            "\u015eikayetlere kurumsal yan\u0131t verme",
        )

        self.assertContains(
            response,
            "Pro firma rozeti",
        )

    def test_dashboard_contains_pro_upgrade_entry(self):
        response = self.client.get(
            reverse("companies:company_panel")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertContains(
            response,
            "MEVCUT PAKET \u00b7 \u00dcCRETS\u0130Z",
        )

        self.assertContains(
            response,
            reverse("companies:plan"),
        )

        self.assertContains(
            response,
            "Pro'yu \u0130ncele",
        )

    def test_mobile_navigation_has_accessible_off_canvas_controls(self):
        response = self.client.get(reverse("companies:company_panel"))
        self.assertContains(response, 'aria-controls="company-navigation"')
        self.assertContains(response, 'aria-expanded="false"')
        self.assertContains(response, 'class="cp-nav-backdrop"')
        self.assertContains(response, 'class="cp-mobile-logout"')
        self.assertContains(response, "Çıkış")
