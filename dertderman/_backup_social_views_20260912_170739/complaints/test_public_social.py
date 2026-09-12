from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.html import escape

from companies.models import Company
from notifications.models import Notification

from .models import Complaint, ComplaintComment, ComplaintLike, ComplaintReaction


User = get_user_model()


class PublicComplaintSocialTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username="public-owner", email="public-owner@example.com", user_type="USER")
        cls.visitor = User.objects.create_user(username="public-visitor", email="public-visitor@example.com", user_type="USER")
        cls.other = User.objects.create_user(username="public-other", email="public-other@example.com", user_type="USER")
        cls.company_user = User.objects.create_user(username="social-company", email="social-company@example.com", user_type="COMPANY")
        cls.admin = User.objects.create_user(username="social-admin", email="social-admin@example.com", user_type="ADMIN")
        cls.company = Company.objects.create(name="Public Social Company", is_verified=True)
        cls.complaint = Complaint.objects.create(
            user=cls.owner, company=cls.company, status=Complaint.Status.PUBLISHED,
            title="Topluluk deneyimi", description="Topluluk özelliklerini doğrulayan yeterince uzun açıklama.",
        )

    def detail(self):
        return reverse("complaints:public_detail", args=[self.complaint.pk])

    def test_like_toggle_count_unique_and_notification_is_not_spammed(self):
        self.client.force_login(self.visitor)
        url = reverse("complaints:like_toggle", args=[self.complaint.pk])
        self.client.post(url)
        self.assertEqual(ComplaintLike.objects.filter(complaint=self.complaint).count(), 1)
        self.assertEqual(Notification.objects.filter(notification_type="LIKE").count(), 1)
        self.client.post(url)
        self.assertFalse(ComplaintLike.objects.filter(complaint=self.complaint).exists())
        self.client.post(url)
        self.assertEqual(ComplaintLike.objects.filter(complaint=self.complaint).count(), 1)
        self.assertEqual(Notification.objects.filter(notification_type="LIKE").count(), 1)
        self.assertContains(self.client.get(self.detail()), "Beğenildi")

    def test_reaction_is_single_updates_and_notifies_once(self):
        self.client.force_login(self.visitor)
        url = reverse("complaints:react", args=[self.complaint.pk])
        self.client.post(url, {"reaction_type": ComplaintReaction.Type.AGREE, "user_id": self.other.pk})
        self.client.post(url, {"reaction_type": ComplaintReaction.Type.SAD})
        reaction = ComplaintReaction.objects.get(complaint=self.complaint)
        self.assertEqual(reaction.user, self.visitor)
        self.assertEqual(reaction.reaction_type, ComplaintReaction.Type.SAD)
        self.assertEqual(ComplaintReaction.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(notification_type="REACTION").count(), 1)
        self.client.post(url, {"reaction_type": ComplaintReaction.Type.SAD})
        self.assertFalse(ComplaintReaction.objects.exists())
        self.client.post(url, {"reaction_type": ComplaintReaction.Type.SURPRISED})
        self.assertEqual(ComplaintReaction.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(notification_type="REACTION").count(), 1)
        self.client.force_login(self.other)
        self.client.post(url, {"reaction_type": ComplaintReaction.Type.AGREE})
        self.assertEqual(ComplaintReaction.objects.count(), 2)
        self.assertEqual(Notification.objects.filter(notification_type="REACTION").count(), 2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ComplaintReaction.objects.create(
                complaint=self.complaint, user=self.other,
                reaction_type=ComplaintReaction.Type.SUPPORT,
            )

    def test_comment_validation_binding_xss_and_notification(self):
        self.client.force_login(self.visitor)
        url = reverse("complaints:comment_create", args=[self.complaint.pk])
        self.assertEqual(self.client.post(url, {"body": "   "}).status_code, 400)
        self.assertFalse(ComplaintComment.objects.exists())
        attack = '<script>alert("comment")</script>'
        response = self.client.post(url, {"body": attack, "author_user": self.other.pk})
        self.assertRedirects(response, self.detail())
        comment = ComplaintComment.objects.get()
        self.assertEqual(comment.author_user, self.visitor)
        detail = self.client.get(self.detail())
        self.assertContains(detail, escape(attack))
        self.assertNotContains(detail, attack)
        self.assertEqual(Notification.objects.filter(notification_type="COMMENT").count(), 1)

    def test_self_actions_never_notify(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("complaints:like_toggle", args=[self.complaint.pk]))
        self.client.post(reverse("complaints:react", args=[self.complaint.pk]), {"reaction_type": "SUPPORT"})
        self.client.post(reverse("complaints:comment_create", args=[self.complaint.pk]), {"body": "Kendi açıklamam için ek bilgi."})
        self.assertFalse(Notification.objects.filter(recipient_user=self.owner, notification_type__in=("LIKE", "REACTION", "COMMENT")).exists())

    def test_comments_are_paginated_ten_per_page(self):
        ComplaintComment.objects.bulk_create([
            ComplaintComment(complaint=self.complaint, author_user=self.visitor, body=f"Yorum {index}")
            for index in range(13)
        ])
        first = self.client.get(self.detail()).context["comment_page"]
        second = self.client.get(self.detail(), {"comment_page": 2}).context["comment_page"]
        self.assertEqual(len(first), 10)
        self.assertEqual(len(second), 3)

    def test_comment_delete_is_owner_scoped_soft_delete_and_post_only(self):
        comment = ComplaintComment.objects.create(
            complaint=self.complaint, author_user=self.visitor, body="Kaldırılacak yorum"
        )
        url = reverse("complaints:comment_delete", args=[self.complaint.pk, comment.pk])
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.force_login(self.visitor)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url), self.detail())
        comment.refresh_from_db()
        self.assertFalse(comment.is_active)
        self.assertNotContains(self.client.get(self.detail()), comment.body)

    def test_social_posts_require_user_role_post_and_csrf(self):
        urls = [
            reverse("complaints:like_toggle", args=[self.complaint.pk]),
            reverse("complaints:react", args=[self.complaint.pk]),
            reverse("complaints:comment_create", args=[self.complaint.pk]),
        ]
        for url in urls:
            self.client.logout()
            self.assertEqual(self.client.post(url).status_code, 302)
            for user in (self.company_user, self.admin):
                self.client.force_login(user)
                self.assertEqual(self.client.post(url).status_code, 403)
            self.client.force_login(self.visitor)
            self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.visitor)
        self.assertEqual(csrf_client.post(urls[0]).status_code, 403)

    def test_nonpublic_complaint_social_routes_are_404(self):
        pending = Complaint.objects.create(
            user=self.owner, company=self.company, title="Henüz özel kayıt",
            description="Henüz yayınlanmamış yeterince uzun açıklama.",
        )
        self.client.force_login(self.visitor)
        for route in ("like_toggle", "react", "comment_create"):
            self.assertEqual(self.client.post(reverse(f"complaints:{route}", args=[pending.pk])).status_code, 404)

    def test_public_list_annotations_do_not_add_per_card_queries(self):
        self.client.get(reverse("complaints:public_list"))
        with CaptureQueriesContext(connection) as one:
            self.client.get(reverse("complaints:public_list"))
        for index in range(7):
            Complaint.objects.create(
                user=self.owner, company=self.company, status=Complaint.Status.PUBLISHED,
                title=f"Performans kaydı {index}", description="Sorgu sayısını doğrulayan açıklama.",
            )
        with CaptureQueriesContext(connection) as many:
            response = self.client.get(reverse("complaints:public_list"))
        self.assertEqual(len(one), len(many))
        self.assertContains(response, "public-two-column")

    def test_homepage_is_newest_first_capped_at_four(self):
        created = [Complaint.objects.create(
            user=self.owner, company=self.company, status=Complaint.Status.PUBLISHED,
            title=f"Yeni kayıt {index}", description="Ana sayfa sıralamasını doğrulayan açıklama.",
        ) for index in range(6)]
        response = self.client.get(reverse("core:home"))
        self.assertEqual(list(response.context["recent_complaints"]), list(reversed(created))[:4])
        self.assertContains(response, "En Güncel Şikayetler")
        self.assertContains(response, "Tüm Şikayetleri Gör")
        self.assertEqual(response.content.decode().count("En Güncel Şikayetler"), 1)


class PublicBrandTests(TestCase):
    def test_public_navbar_uses_compact_brand_and_intro_restores_wordmark(self):
        home = self.client.get(reverse("core:home"))
        intro = self.client.get(reverse("core:intro"), {"preview": 1})
        self.assertContains(home, "compact-brand-symbol")
        self.assertContains(home, "Paylaşmadan Olmaz")
        self.assertContains(intro, "intro-wordmark__dert")
        self.assertContains(intro, "intro-wordmark__derman")
        self.assertNotContains(intro, "dert_derman.jpeg")
