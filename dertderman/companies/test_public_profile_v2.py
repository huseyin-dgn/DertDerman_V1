from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from complaints.models import (
    Complaint,
    ComplaintComment,
    ComplaintEvent,
    ComplaintLike,
    ComplaintReaction,
)

from .models import Company, CompanyCategory, CompanyResponse, InternalCompanyNote


User = get_user_model()


class PublicCompanyProfileV2Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="profile-reader",
            email="reader@example.com",
            password="StrongPass2026!",
            user_type="USER",
        )
        cls.company_user = User.objects.create_user(
            username="profile-company",
            email="company-user@example.com",
            password="StrongPass2026!",
            user_type="COMPANY",
        )
        cls.category = CompanyCategory.objects.create(name="Teknoloji")
        cls.company = Company.objects.create(
            name="Mavi Teknoloji",
            description="Tüketici odaklı teknoloji hizmetleri.",
            website="https://example.com",
            email="destek@example.com",
            phone="+905551112233",
            category=cls.category,
            is_verified=True,
            approval_status=Company.ApprovalStatus.APPROVED,
        )
        cls.url = reverse(
            "companies_public:company_detail", kwargs={"slug": cls.company.slug}
        )

    def complaint(self, title, status=Complaint.Status.PUBLISHED, company=None):
        return Complaint.objects.create(
            user=self.owner,
            company=company or self.company,
            title=title,
            description=f"{title} için yeterince uzun ve açıklayıcı tüketici deneyimi.",
            status=status,
        )

    def response(self, complaint, *, active=True, body="Çözüm odaklı şirket yanıtı."):
        return CompanyResponse.objects.create(
            complaint=complaint,
            company=complaint.company,
            author_user=self.company_user,
            body=body,
            is_active=active,
        )

    def test_correct_company_profile_and_verified_help_are_rendered(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.company.name)
        self.assertContains(response, self.category.name)
        self.assertContains(response, "Bu şirket hesabı DertDerman'da doğrulanmıştır.")
        self.assertContains(response, "https://example.com")
        self.assertContains(response, f"?company={self.company.pk}")

    def test_unverified_company_does_not_receive_fake_badge(self):
        self.company.is_verified = False
        self.company.save(update_fields=("is_verified",))

        response = self.client.get(self.url)

        self.assertNotContains(response, "Doğrulanmış şirket")

    def test_inactive_unapproved_and_archived_company_profiles_are_not_public(self):
        cases = (
            {"is_active": False},
            {"approval_status": Company.ApprovalStatus.PENDING},
            {"archived_at": timezone.now()},
        )
        for index, changes in enumerate(cases):
            company = Company.objects.create(
                name=f"Gizli Şirket {index}", category=self.category, **changes
            )
            with self.subTest(changes=changes):
                self.assertEqual(
                    self.client.get(reverse(
                        "companies_public:company_detail",
                        kwargs={"slug": company.slug},
                    )).status_code,
                    404,
                )

    def test_metrics_use_only_public_complaints_and_first_active_response(self):
        now = timezone.now().replace(second=0, microsecond=0)
        first = self.complaint("İlk public kayıt")
        second = self.complaint("İkinci public kayıt")
        resolved = self.complaint("Çözülen public kayıt", Complaint.Status.RESOLVED)
        self.complaint("Bekleyen gizli kayıt", Complaint.Status.PENDING)
        self.complaint("Reddedilen gizli kayıt", Complaint.Status.REJECTED)

        for index, complaint in enumerate((first, second, resolved)):
            published_at = now + timedelta(days=index)
            Complaint.objects.filter(pk=complaint.pk).update(
                created_at=published_at - timedelta(hours=1)
            )
            ComplaintEvent.objects.filter(
                complaint=complaint, event_type=ComplaintEvent.Type.PUBLISHED
            ).update(occurred_at=published_at)

        inactive_reply = self.response(first, active=False, body="Eski pasif yanıt")
        CompanyResponse.objects.filter(pk=inactive_reply.pk).update(
            created_at=now + timedelta(minutes=10)
        )
        first_reply = self.response(first)
        second_reply = self.response(second)
        later_reply = self.response(first, body="Daha sonraki aktif yanıt")
        CompanyResponse.objects.filter(pk=first_reply.pk).update(
            created_at=now + timedelta(hours=2)
        )
        CompanyResponse.objects.filter(pk=second_reply.pk).update(
            created_at=now + timedelta(days=1, hours=4)
        )
        CompanyResponse.objects.filter(pk=later_reply.pk).update(
            created_at=now + timedelta(hours=8)
        )

        response = self.client.get(self.url)
        metrics = response.context["performance"]

        self.assertEqual(metrics["total"], 3)
        self.assertEqual(metrics["answered"], 2)
        self.assertEqual(metrics["response_ratio"], 67)
        self.assertEqual(metrics["resolved"], 1)
        self.assertEqual(metrics["resolved_ratio"], 33)
        self.assertEqual(response.context["average_response"], "3 sa")

    def test_no_data_fallback_is_clear(self):
        response = self.client.get(self.url)

        self.assertEqual(response.context["performance"]["total"], 0)
        self.assertIsNone(response.context["average_response"])
        self.assertContains(response, "Henüz yeterli veri yok", count=4)

    def test_only_this_company_public_complaints_and_no_internal_note_are_rendered(self):
        visible = self.complaint("Görünen yayın")
        solved = self.complaint("Görünen çözüm", Complaint.Status.RESOLVED)
        pending = self.complaint("Gizli bekleyen", Complaint.Status.PENDING)
        rejected = self.complaint("Gizli reddedilen", Complaint.Status.REJECTED)
        other = Company.objects.create(name="Başka Şirket", category=self.category)
        foreign = self.complaint("Başka şirket kaydı", company=other)
        InternalCompanyNote.objects.create(
            complaint=visible,
            company=self.company,
            author_user=self.company_user,
            body="ÇOK GİZLİ DAHİLİ NOT",
        )

        response = self.client.get(self.url)

        self.assertContains(response, visible.title)
        self.assertContains(response, solved.title)
        self.assertNotContains(response, pending.title)
        self.assertNotContains(response, rejected.title)
        self.assertNotContains(response, foreign.title)
        self.assertNotContains(response, "ÇOK GİZLİ DAHİLİ NOT")

    def test_complaint_cards_show_social_counts_without_extra_queries(self):
        complaint = self.complaint("Etkileşimli kayıt")
        ComplaintLike.objects.create(complaint=complaint, user=self.owner)
        ComplaintReaction.objects.create(
            complaint=complaint,
            user=self.owner,
            reaction_type=ComplaintReaction.Type.SUPPORT,
        )
        ComplaintComment.objects.create(
            complaint=complaint,
            author_user=self.owner,
            body="Bu deneyimi ben de yaşadım.",
        )
        with CaptureQueriesContext(connection) as first_queries:
            response = self.client.get(self.url)
            self.assertContains(response, "♡ 1 · Tepki 1 · Yorum 1")

        for index in range(8):
            self.complaint(f"Sabit sorgu testi {index}")
        with CaptureQueriesContext(connection) as populated_queries:
            self.client.get(self.url)

        self.assertEqual(len(populated_queries), len(first_queries))

    def test_complaints_are_newest_first_and_paginated_six_per_page(self):
        complaints = [self.complaint(f"Sayfalama kaydı {index}") for index in range(7)]

        first_page = self.client.get(self.url)
        second_page = self.client.get(self.url, {"page": 2})

        self.assertEqual(len(first_page.context["page_obj"]), 6)
        self.assertEqual(len(second_page.context["page_obj"]), 1)
        self.assertEqual(first_page.context["page_obj"][0], complaints[-1])
        self.assertContains(first_page, "›")

    def test_answered_and_resolved_filters_work_and_pagination_keeps_filter(self):
        answered = self.complaint("Yanıtlanan kayıt")
        self.response(answered)
        resolved = self.complaint("Çözülen kayıt", Complaint.Status.RESOLVED)
        plain = self.complaint("Sadece yayınlanan kayıt")
        for index in range(6):
            item = self.complaint(f"Yanıtlanan ek kayıt {index}")
            self.response(item)

        answered_page = self.client.get(self.url, {"status": "answered"})
        resolved_page = self.client.get(self.url, {"status": "resolved"})

        self.assertTrue(answered_page.context["page_obj"])
        self.assertTrue(all(item.has_response for item in answered_page.context["page_obj"]))
        self.assertNotContains(answered_page, plain.title)
        self.assertContains(answered_page, "status=answered&amp;page=2")
        self.assertContains(resolved_page, resolved.title)
        self.assertNotContains(resolved_page, plain.title)

    def test_recent_response_previews_are_public_active_and_capped_at_four(self):
        for index in range(5):
            self.response(self.complaint(f"Public yanıt kaydı {index}"), body=f"PUBLIC RESPONSE {index}")
        pending = self.complaint("Private response complaint", Complaint.Status.PENDING)
        self.response(pending, body="PRIVATE RESPONSE")
        inactive = self.complaint("Inactive response complaint")
        self.response(inactive, active=False, body="INACTIVE RESPONSE")

        response = self.client.get(self.url)

        self.assertEqual(len(response.context["recent_responses"]), 4)
        self.assertNotContains(response, "PRIVATE RESPONSE")
        self.assertNotContains(response, "INACTIVE RESPONSE")

    def test_user_cta_preselects_public_company_and_anonymous_keeps_login_flow(self):
        create_url = reverse("complaints:create") + f"?company={self.company.pk}"
        anonymous = self.client.get(create_url)
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn("next=", anonymous["Location"])

        self.client.force_login(self.owner)
        response = self.client.get(create_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["company"], self.company)
