from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from companies.management.commands.seed_demo_companies import DEMO_COMPANY_NAMES
from companies.models import Company, CompanyMembership
from complaints.models import Complaint


class DemoCompanyCommandTests(TestCase):
    @override_settings(DEBUG=False)
    def test_production_is_rejected_before_database_access(self):
        with self.assertNumQueries(0):
            with self.assertRaisesMessage(CommandError, "yalnızca DEBUG=True"):
                call_command("seed_demo_companies", stdout=StringIO())

    @override_settings(DEBUG=True)
    def test_repeated_runs_reuse_demo_records_without_other_seed_data(self):
        existing = Company.objects.create(name="Existing company", is_active=False)
        call_command("seed_demo_companies", stdout=StringIO())
        original_ids = set(Company.objects.filter(name__in=DEMO_COMPANY_NAMES).values_list("pk", flat=True))
        Company.objects.filter(name=DEMO_COMPANY_NAMES[0]).update(is_active=False)
        call_command("seed_demo_companies", stdout=StringIO())
        demos = Company.objects.filter(name__in=DEMO_COMPANY_NAMES)
        self.assertEqual(set(demos.values_list("pk", flat=True)), original_ids)
        self.assertEqual(demos.count(), 5)
        self.assertEqual(demos.filter(is_active=True).count(), 5)
        self.assertEqual(Company.objects.count(), 6)
        existing.refresh_from_db()
        self.assertFalse(existing.is_active)
        self.assertEqual(get_user_model().objects.count(), 0)
        self.assertEqual(CompanyMembership.objects.count(), 0)
        self.assertEqual(Complaint.objects.count(), 0)

    @override_settings(DEBUG=True)
    def test_demo_companies_appear_in_authorized_form_and_public_pages(self):
        call_command("seed_demo_companies", stdout=StringIO())
        user = get_user_model().objects.create_user(username="demo-form-reader", user_type="USER")
        self.client.force_login(user)
        response = self.client.get("/sikayet-olustur/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertSetEqual(set(response.context["form"].fields["company"].queryset.values_list("name", flat=True)), set(DEMO_COMPANY_NAMES))
        for company in Company.objects.all():
            self.assertContains(response, f'<option value="{company.pk}">{company.name}</option>', html=True)
            self.assertContains(self.client.get("/sirketler/"), company.name)
            self.assertEqual(self.client.get(reverse("companies_public:company_detail", args=[company.slug])).status_code, 200)
