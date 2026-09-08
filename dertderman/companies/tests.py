from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import Company, CompanyCategory, CompanyMembership


User = get_user_model()


class CompanyDomainTests(TestCase):
    def create_user(self, username, user_type):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="StrongPass2026!",
            user_type=user_type,
        )

    def create_company(self, name="Acme"):
        category = CompanyCategory.objects.create(name=f"{name} Category")
        return Company.objects.create(
            name=name,
            description=f"{name} description",
            email=f"{name.lower()}@example.com",
            phone="5551234567",
            category=category,
            is_verified=True,
        )

    def test_company_category_can_be_created(self):
        category = CompanyCategory.objects.create(name="Elektronik")

        self.assertEqual(category.name, "Elektronik")
        self.assertTrue(category.slug)
        self.assertTrue(category.is_active)

    def test_company_can_be_created(self):
        category = CompanyCategory.objects.create(name="Teknoloji")

        company = Company.objects.create(
            name="DertDerman Test Şirketi",
            description="Public açıklama",
            website="https://example.com",
            email="company@example.com",
            phone="5551234567",
            category=category,
        )

        self.assertEqual(company.name, "DertDerman Test Şirketi")
        self.assertTrue(company.slug)
        self.assertFalse(company.is_verified)
        self.assertTrue(company.is_active)
        self.assertEqual(company.category, category)

    def test_membership_can_be_created(self):
        user = self.create_user("company-owner", User.UserType.COMPANY)
        company = self.create_company("Membership Company")

        membership = CompanyMembership.objects.create(
            user=user,
            company=company,
            role=CompanyMembership.Role.OWNER,
        )

        self.assertEqual(membership.user, user)
        self.assertEqual(membership.company, company)
        self.assertEqual(membership.role, CompanyMembership.Role.OWNER)
        self.assertTrue(membership.is_active)

    def test_duplicate_membership_is_blocked_by_database_constraint(self):
        user = self.create_user("duplicate-member", User.UserType.COMPANY)
        company = self.create_company("Duplicate Membership Company")
        CompanyMembership.objects.create(user=user, company=company)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CompanyMembership.objects.create(user=user, company=company)

    def test_user_type_validation_does_not_elevate_user(self):
        user = self.create_user("normal-member", User.UserType.USER)
        company = self.create_company("No Elevation Company")
        membership = CompanyMembership(user=user, company=company)

        with self.assertRaisesMessage(ValidationError, "COMPANY"):
            membership.full_clean()

        user.refresh_from_db()
        self.assertEqual(user.user_type, User.UserType.USER)

    def test_membership_does_not_grant_company_panel_to_regular_user(self):
        user = self.create_user("regular-with-membership", User.UserType.USER)
        company = self.create_company("Regular Membership Company")
        CompanyMembership.objects.create(user=user, company=company)
        self.client.force_login(user)

        response = self.client.get(reverse("companies:company_panel"))

        self.assertEqual(response.status_code, 403)
        user.refresh_from_db()
        self.assertEqual(user.user_type, User.UserType.USER)

    def test_anonymous_company_panel_redirects_to_login(self):
        response = self.client.get(reverse("companies:company_panel"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_regular_user_cannot_access_company_panel(self):
        user = self.create_user("regular-user", User.UserType.USER)
        self.client.force_login(user)

        response = self.client.get(reverse("companies:company_panel"))

        self.assertEqual(response.status_code, 403)

    def test_company_user_without_membership_cannot_access_company_panel(self):
        user = self.create_user("company-no-membership", User.UserType.COMPANY)
        self.client.force_login(user)

        response = self.client.get(reverse("companies:company_panel"))

        self.assertEqual(response.status_code, 403)

    def test_company_user_with_active_membership_can_access_company_panel(self):
        user = self.create_user("company-with-membership", User.UserType.COMPANY)
        company = self.create_company("Active Membership Company")
        CompanyMembership.objects.create(user=user, company=company, is_active=True)
        self.client.force_login(user)

        response = self.client.get(reverse("companies:company_panel"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, company.name)

    def test_company_user_with_inactive_membership_cannot_access_company_panel(self):
        user = self.create_user("company-inactive-membership", User.UserType.COMPANY)
        company = self.create_company("Inactive Membership Company")
        CompanyMembership.objects.create(user=user, company=company, is_active=False)
        self.client.force_login(user)

        response = self.client.get(reverse("companies:company_panel"))

        self.assertEqual(response.status_code, 403)

    def test_cross_company_object_access_is_forbidden(self):
        user_a = self.create_user("company-user-a", User.UserType.COMPANY)
        user_b = self.create_user("company-user-b", User.UserType.COMPANY)
        company_a = self.create_company("Company A")
        company_b = self.create_company("Company B")
        CompanyMembership.objects.create(user=user_a, company=company_a)
        CompanyMembership.objects.create(user=user_b, company=company_b)
        self.client.force_login(user_a)

        own_response = self.client.get(
            reverse("companies:company_panel_detail", kwargs={"slug": company_a.slug})
        )
        forbidden_response = self.client.get(
            reverse("companies:company_panel_detail", kwargs={"slug": company_b.slug})
        )

        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(forbidden_response.status_code, 403)

    def test_public_company_list_shows_only_active_companies(self):
        active_company = self.create_company("Active Public Company")
        inactive_company = self.create_company("Inactive Public Company")
        inactive_company.is_active = False
        inactive_company.save()

        response = self.client.get(reverse("companies_public:company_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, active_company.name)
        self.assertNotContains(response, inactive_company.name)

    def test_public_company_detail_shows_only_active_companies(self):
        active_company = self.create_company("Active Detail Company")
        inactive_company = self.create_company("Inactive Detail Company")
        inactive_company.is_active = False
        inactive_company.save()

        active_response = self.client.get(
            reverse("companies_public:company_detail", kwargs={"slug": active_company.slug})
        )
        inactive_response = self.client.get(
            reverse(
                "companies_public:company_detail",
                kwargs={"slug": inactive_company.slug},
            )
        )

        self.assertEqual(active_response.status_code, 200)
        self.assertContains(active_response, active_company.name)
        self.assertEqual(inactive_response.status_code, 404)
