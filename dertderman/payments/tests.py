from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from companies.models import (
    Company,
    CompanyCategory,
    CompanyMembership,
    CompanySubscription,
)


User = get_user_model()


class PaymentPreviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="payment-owner",
            email="payment-owner@example.com",
            password="StrongPass2026!",
            user_type=User.UserType.COMPANY,
            is_verified=True,
        )

        self.category = CompanyCategory.objects.create(
            name="Payment Test Category",
        )

        self.company = Company.objects.create(
            name="Payment Test Company",
            category=self.category,
            is_active=True,
            is_verified=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )

        self.membership = CompanyMembership.objects.create(
            user=self.user,
            company=self.company,
            role=CompanyMembership.Role.OWNER,
            is_active=True,
        )

        self.client.force_login(self.user)

    def test_owner_can_open_payment_preview(self):
        response = self.client.get(
            reverse("payments:checkout")
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "payments/payment.html",
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
            "₺499,90",
        )

    def test_yearly_period_is_selected_from_safe_get_parameter(self):
        response = self.client.get(
            reverse("payments:checkout"),
            {"period": "yearly"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["selected_billing"],
            "yearly",
        )
        self.assertEqual(
            response.context["payment_option"]["price"],
            "499,90",
        )

    def test_invalid_period_falls_back_to_monthly(self):
        response = self.client.get(
            reverse("payments:checkout"),
            {"period": "tampered-value"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["selected_billing"],
            "monthly",
        )
        self.assertEqual(
            response.context["payment_option"]["price"],
            "49,90",
        )

    def test_support_member_cannot_open_billing_screen(self):
        self.membership.role = CompanyMembership.Role.SUPPORT
        self.membership.save(update_fields=("role",))

        response = self.client.get(
            reverse("payments:checkout")
        )

        self.assertEqual(response.status_code, 403)

    def test_active_pro_company_is_redirected_to_plan_page(self):
        CompanySubscription.objects.create(
            company=self.company,
            plan=CompanySubscription.Plan.PRO,
            billing_period=CompanySubscription.BillingPeriod.MONTHLY,
            is_active=True,
        )

        response = self.client.get(
            reverse("payments:checkout")
        )

        self.assertRedirects(
            response,
            reverse("companies:plan"),
        )

    def test_preview_does_not_collect_card_credentials(self):
        response = self.client.get(
            reverse("payments:checkout")
        )

        self.assertNotContains(
            response,
            'name="card_number"',
        )
        self.assertNotContains(
            response,
            'name="cvv"',
        )
        self.assertNotContains(
            response,
            'name="card_holder"',
        )
        self.assertContains(
            response,
            "Ödeme altyapısı hazırlanıyor",
        )

    def test_plan_page_links_to_payment_preview(self):
        response = self.client.get(
            reverse("companies:plan")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse("payments:checkout"),
        )
        self.assertContains(
            response,
            "Pro'ya Yükselt",
        )

