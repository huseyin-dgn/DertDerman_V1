from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from difflib import SequenceMatcher
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from companies.models import Company
from core.models import AbuseAttempt

from .anti_abuse import (
    FORM_SESSION_KEY,
    _find_duplicate_or_similar_complaint,
    _similarity_if_possible,
)
from .forms import ComplaintEditForm, MAX_COMPLAINT_DESCRIPTION_LENGTH
from .models import Complaint


User = get_user_model()


class ComplaintCreationPerformanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="creation-performance",
            email="creation-performance@example.com",
            password="StrongPass2026!",
            user_type=User.UserType.USER,
            is_verified=True,
        )
        User.objects.filter(pk=cls.user.pk).update(
            date_joined=timezone.now() - timedelta(days=2)
        )
        cls.company = Company.objects.create(name="Performance Company")

    def setUp(self):
        self.client.force_login(self.user)
        self.client.get(reverse("complaints:create"))
        session = self.client.session
        session[FORM_SESSION_KEY] = (timezone.now() - timedelta(seconds=2)).timestamp()
        session.save()

    def data(self, description="Açıklama yeterince uzun ve anlaşılırdır."):
        return {
            "company": self.company.pk,
            "category": Complaint.Category.OTHER,
            "title": "Yeni teslimat sorunu",
            "description": description,
        }

    def previous(self, *, age=timedelta(hours=2), status=Complaint.Status.RESOLVED,
                 description="Önceki teslimat için yeterince uzun açıklama.", company=None):
        complaint = Complaint.objects.create(
            user=self.user,
            company=company or self.company,
            title="Önceki teslimat sorunu",
            description=description,
            status=status,
        )
        Complaint.objects.filter(pk=complaint.pk).update(
            created_at=timezone.now() - age
        )
        return complaint

    def test_overlong_post_and_edit_form_reject_before_similarity(self):
        description = "a" * (MAX_COMPLAINT_DESCRIPTION_LENGTH + 1)
        with patch("complaints.anti_abuse._find_duplicate_or_similar_complaint") as find:
            response = self.client.post(reverse("complaints:create"), self.data(description))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Açıklama en fazla 4000 karakter olabilir.", response.context["form"].errors["description"])
        self.assertFalse(Complaint.objects.exists())
        find.assert_not_called()
        self.assertEqual(
            response.context["form"].fields["description"].widget.attrs["maxlength"],
            MAX_COMPLAINT_DESCRIPTION_LENGTH,
        )
        self.assertIn("description", ComplaintEditForm(data=self.data(description)).errors)

    def test_cooldown_skips_similarity(self):
        self.previous(age=timedelta(minutes=1))
        with patch("complaints.anti_abuse._find_duplicate_or_similar_complaint") as find:
            response = self.client.post(reverse("complaints:create"), self.data())
        self.assertEqual(response.status_code, 429)
        self.assertEqual(AbuseAttempt.objects.latest("pk").event_type,
                         AbuseAttempt.EventType.SAME_COMPANY_COOLDOWN)
        find.assert_not_called()

    def test_open_limit_skips_similarity(self):
        for index in range(5):
            self.previous(age=timedelta(days=index + 2), status=Complaint.Status.PENDING,
                          description=f"Açık şikayet {index} için farklı açıklama.")
        with patch("complaints.anti_abuse._find_duplicate_or_similar_complaint") as find:
            response = self.client.post(reverse("complaints:create"), self.data())
        self.assertEqual(response.status_code, 429)
        self.assertEqual(AbuseAttempt.objects.latest("pk").event_type,
                         AbuseAttempt.EventType.OPEN_COMPLAINT_LIMIT)
        find.assert_not_called()

    def test_ten_minute_limit_skips_similarity(self):
        other = Company.objects.create(name="Other Performance Company")
        self.previous(age=timedelta(minutes=2), company=other)
        self.previous(age=timedelta(minutes=3), company=other)
        with patch("complaints.anti_abuse._find_duplicate_or_similar_complaint") as find:
            response = self.client.post(reverse("complaints:create"), self.data())
        self.assertEqual(response.status_code, 429)
        self.assertEqual(AbuseAttempt.objects.latest("pk").event_type,
                         AbuseAttempt.EventType.COMPLAINT_RATE_LIMIT_10M)
        find.assert_not_called()

    def test_valid_4000_character_post_checks_similarity_and_creates(self):
        description = "Teslimat gecikti. " * 222 + "bitti."
        description = description[:MAX_COMPLAINT_DESCRIPTION_LENGTH]
        with patch("complaints.anti_abuse._find_duplicate_or_similar_complaint", return_value=None) as find:
            response = self.client.post(reverse("complaints:create"), self.data(description))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Complaint.objects.count(), 1)
        find.assert_called_once()

    def test_exact_duplicate_and_similar_still_blocked(self):
        original = "Sipariş teslim edilmedi, teslimat tarihi geçti ve destek yanıt vermedi."
        self.previous(description=original)
        duplicate = self.client.post(reverse("complaints:create"), self.data(original))
        self.assertEqual(duplicate.status_code, 429)
        self.assertEqual(AbuseAttempt.objects.latest("pk").event_type,
                         AbuseAttempt.EventType.DUPLICATE_COMPLAINT)
        session = self.client.session
        session[FORM_SESSION_KEY] = (timezone.now() - timedelta(seconds=2)).timestamp()
        session.save()
        similar = self.client.post(
            reverse("complaints:create"), self.data(original + " Hâlâ bekliyorum.")
        )
        self.assertEqual(similar.status_code, 429)
        self.assertEqual(AbuseAttempt.objects.latest("pk").event_type,
                         AbuseAttempt.EventType.SIMILAR_COMPLAINT)
        self.assertEqual(Complaint.objects.count(), 1)

    def test_similarity_candidate_window_retains_old_record(self):
        old = self.previous(age=timedelta(days=100), description="Teslim edilmeyen ürün için eski açıklama.")
        for index in range(6):
            self.previous(age=timedelta(days=index + 2),
                          description=f"Farklı gönderi {index} hakkında açıklama.")
        result = _find_duplicate_or_similar_complaint(
            user=self.user, company=self.company, title="Başka başlık",
            description=old.description,
        )
        self.assertEqual(result["type"], "duplicate")
        self.assertEqual(result["complaint_id"], old.pk)

    def test_lcs_bound_skips_expensive_ratio_without_losing_near_matches(self):
        class CountingMatcher(SequenceMatcher):
            ratio_calls = 0

            def ratio(self):
                type(self).ratio_calls += 1
                return super().ratio()

        with patch("complaints.anti_abuse.SequenceMatcher", CountingMatcher):
            self.assertEqual(
                _similarity_if_possible("a" * 2000 + "b" * 2000,
                                        "b" * 2000 + "a" * 2000),
                0.0,
            )
            self.assertEqual(CountingMatcher.ratio_calls, 0)
            self.assertGreaterEqual(
                _similarity_if_possible("a" * 2000 + "b" * 2000,
                                        "a" * 1999 + "c" + "b" * 2000),
                0.85,
            )
            self.assertEqual(CountingMatcher.ratio_calls, 1)


class ConcurrentComplaintCreationTests(TransactionTestCase):
    def test_same_user_requests_serialize_and_only_first_checks_similarity(self):
        user = User.objects.create_user(
            username="concurrent-creator",
            email="concurrent-creator@example.com",
            password="StrongPass2026!",
            user_type=User.UserType.USER,
            is_verified=True,
        )
        company = Company.objects.create(name="Concurrent Company")
        clients = []
        for _ in range(4):
            client = Client()
            client.force_login(user)
            client.get(reverse("complaints:create"))
            session = client.session
            session[FORM_SESSION_KEY] = (timezone.now() - timedelta(seconds=2)).timestamp()
            session.save()
            clients.append(client)

        def submit(client):
            try:
                response = client.post(reverse("complaints:create"), {
                    "company": company.pk,
                    "category": Complaint.Category.OTHER,
                    "title": "Eşzamanlı teslimat sorunu",
                    "description": "Siparişim teslim edilmedi ve açıklama bekliyorum.",
                })
                return response.status_code
            finally:
                connections.close_all()

        with patch("complaints.anti_abuse._find_duplicate_or_similar_complaint", return_value=None) as find:
            with ThreadPoolExecutor(max_workers=4) as executor:
                statuses = list(executor.map(submit, clients))

        self.assertEqual(sorted(statuses), [302, 429, 429, 429])
        self.assertEqual(Complaint.objects.filter(user=user).count(), 1)
        self.assertEqual(find.call_count, 1)
