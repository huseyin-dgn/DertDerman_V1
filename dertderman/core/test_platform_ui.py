from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import Company
from complaints.models import Complaint
from complaints.selectors import public_complaints


class PlatformPresentationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="platform-reader", user_type="USER")
        cls.company = Company.objects.create(name="Platform Company")
        cls.inactive = Company.objects.create(name="Inactive Company", is_active=False)
        cls.complaints = {
            status: Complaint.objects.create(user=cls.user, company=cls.company, status=status,
                title=f"Complaint {status}", description="Private description must not appear in activity.")
            for status in Complaint.Status.values
        }
        cls.hidden = Complaint.objects.create(user=cls.user, company=cls.inactive,
            status=Complaint.Status.PUBLISHED, title="Hidden company complaint", description="Hidden content.")

    def test_metrics_use_actual_counts_without_exposing_private_records(self):
        response = self.client.get("/")
        self.assertEqual(response.context["stats"], {
            "total_complaints": 5, "companies": 2, "users": 1, "published": 1, "resolved": 1,
        })
        self.assertContains(response, 'data-count="5"')
        self.assertNotContains(response, self.complaints["PENDING"].title)
        self.assertNotContains(response, self.complaints["REJECTED"].title)
        self.assertNotContains(response, self.complaints["RESOLVED"].title)
        self.assertNotContains(response, self.hidden.title)

    def test_empty_metrics_are_zero(self):
        Complaint.objects.all().delete()
        Company.objects.all().delete()
        get_user_model().objects.all().delete()
        response = self.client.get("/")
        self.assertEqual(set(response.context["stats"].values()), {0})

    def test_company_activity_is_public_limited_and_has_constant_queries(self):
        for index in range(7):
            Complaint.objects.create(user=self.user, company=self.company, status=Complaint.Status.PUBLISHED,
                title=f"Recent complaint {index}", description="A public complaint description.")
        url = reverse("companies_public:company_detail", args=[self.company.slug])
        with self.assertNumQueries(2):
            response = self.client.get(url)
        entries = list(response.context["recent_public_complaints"])
        self.assertEqual(len(entries), 5)
        self.assertEqual([entry.title for entry in entries], [f"Recent complaint {index}" for index in range(6, 1, -1)])
        for status in ["PENDING", "REJECTED", "RESOLVED"]:
            self.assertNotContains(response, self.complaints[status].title)
            self.assertEqual(self.client.get(reverse("complaints:public_detail", args=[self.complaints[status].pk])).status_code, 404)
        self.assertNotContains(response, self.hidden.title)
        self.assertEqual(self.client.get(reverse("companies_public:company_detail", args=[self.inactive.slug])).status_code, 404)

    def test_activity_date_is_creation_not_publication_or_update(self):
        complaint = self.complaints["PUBLISHED"]
        created = timezone.now() - timedelta(days=30)
        updated = timezone.now() - timedelta(days=2)
        Complaint.objects.filter(pk=complaint.pk).update(created_at=created, updated_at=updated)
        response = self.client.get(reverse("companies_public:company_detail", args=[self.company.slug]))
        self.assertContains(response, "Yayındaki şikayet")
        self.assertContains(response, "Oluşturulma:")
        self.assertContains(response, timezone.localtime(created).strftime("%d.%m.%Y"))
        self.assertNotContains(response, timezone.localtime(updated).strftime("%d.%m.%Y"))
        self.assertNotContains(response, "yayınlandı")
        self.assertNotContains(response, complaint.description)
        self.assertEqual(list(public_complaints()), [complaint])

    def test_lifecycle_uses_current_status_without_invented_history(self):
        self.client.force_login(self.user)
        for status, complaint in self.complaints.items():
            with self.subTest(status=status):
                response = self.client.get(reverse("complaints:detail", args=[complaint.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response["Cache-Control"])
                self.assertContains(response, 'aria-current="step"', count=1)
                self.assertContains(response, complaint.get_status_display())
                self.assertContains(response, "Gönderildi")
                self.assertNotContains(response, "Şirket Yanıtladı")
                if status in ["RESOLVED", "REJECTED"]:
                    self.assertNotContains(response, "Bekleniyor")
                    self.assertNotContains(response, ">Yayında<")
