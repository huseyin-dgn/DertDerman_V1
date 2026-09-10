from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.badges import resolve_badges_for_users, resolve_user_badges
from companies.models import Company, CompanyMembership
from complaints.models import Complaint, ComplaintComment, ComplaintReaction
from core.models import ContactRequest


User = get_user_model()
PASSWORD = "StrongPass2026!"


class AvatarFinalizationTests(TestCase):
    def registration_data(self, **overrides):
        data = {
            "username": "avatar-user", "email": "avatar@example.com",
            "password1": PASSWORD, "password2": PASSWORD, "selected_avatar": "avatar-12",
        }
        data.update(overrides)
        return data

    def test_register_requires_whitelisted_avatar_and_renders_twenty_assets(self):
        page = self.client.get(reverse("accounts:register"))
        self.assertContains(page, "images/avatars/users/avatar-", count=20)
        self.assertNotContains(page, 'type="file"')
        response = self.client.post(reverse("accounts:register"), self.registration_data(selected_avatar=""))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="avatar-user").exists())
        for invalid in ("../companies/company-1", "/static/private.svg", "avatar-99"):
            response = self.client.post(reverse("accounts:register"), self.registration_data(selected_avatar=invalid))
            self.assertEqual(response.status_code, 200)
            self.assertIn("selected_avatar", response.context["form"].errors)

    def test_valid_registration_and_profile_avatar_change_ignore_badge_and_upload(self):
        self.assertRedirects(
            self.client.post(reverse("accounts:register"), self.registration_data()),
            reverse("dashboard:home"),
        )
        user = User.objects.get(username="avatar-user")
        self.assertEqual(user.selected_avatar, "avatar-12")
        response = self.client.post(reverse("accounts:profile_edit"), {
            "email": user.email, "selected_avatar": "avatar-20",
            "profile_image": "users/profile-images/injected.svg", "badge": "solution-focused",
        })
        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertEqual(user.selected_avatar, "avatar-20")
        self.assertFalse(user.profile_image)
        page = self.client.get(reverse("accounts:profile_edit"))
        self.assertNotContains(page, 'type="file"')
        self.assertNotContains(page, "badge")

    def test_company_avatar_set_is_separate_and_membership_is_enforced(self):
        owner = User.objects.create_user(username="company-owner", email="co@example.com", password=PASSWORD, user_type="COMPANY")
        support = User.objects.create_user(username="company-support", email="support@example.com", password=PASSWORD, user_type="COMPANY")
        company = Company.objects.create(name="Geometrik Marka", is_verified=True)
        CompanyMembership.objects.create(user=owner, company=company, role="OWNER")
        CompanyMembership.objects.create(user=support, company=company, role="SUPPORT")
        self.client.force_login(owner)
        response = self.client.post(reverse("companies:profile"), {"name": company.name, "selected_avatar": "company-6"})
        self.assertRedirects(response, reverse("companies:profile"))
        company.refresh_from_db()
        self.assertEqual(company.selected_avatar, "company-6")
        public = self.client.get(reverse("companies_public:company_detail", args=[company.slug]))
        self.assertContains(public, "images/avatars/companies/company-6.svg")
        self.assertNotContains(public, "images/avatars/users/company-6.svg")
        response = self.client.post(reverse("companies:profile"), {"name": company.name, "selected_avatar": "avatar-1"})
        self.assertEqual(response.status_code, 400)
        self.client.force_login(support)
        self.assertEqual(self.client.post(reverse("companies:profile"), {"name": company.name, "selected_avatar": "company-2"}).status_code, 403)


class BadgeResolverTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="badge-user", email="badge@example.com", user_type="USER", selected_avatar="avatar-3")
        User.objects.filter(pk=cls.user.pk).update(date_joined=timezone.now() - timedelta(days=370))
        cls.user.refresh_from_db()
        cls.company = Company.objects.create(name="Badge Company")
        cls.complaints = [Complaint.objects.create(
            user=cls.user, company=cls.company, title=f"Badge complaint {index}",
            description="Badge eligibility için yeterli public deneyim açıklaması.",
            status=Complaint.Status.RESOLVED if index < 3 else Complaint.Status.PUBLISHED,
        ) for index in range(10)]
        for index, complaint in enumerate(cls.complaints):
            commenter = User.objects.create_user(username=f"badge-helper-{index}", email=f"helper-{index}@example.com", user_type="USER")
            ComplaintComment.objects.create(complaint=complaint, author_user=cls.user, body="Topluluk katkısı")
            ComplaintReaction.objects.create(complaint=complaint, user=cls.user, reaction_type="👍")

    def test_badges_use_real_database_thresholds(self):
        keys = {badge.key for badge in resolve_user_badges(self.user)}
        self.assertEqual(keys, {
            "new-contributor", "contributor", "active-contributor", "solution-focused",
            "community-supporter", "long-standing",
        })
        Complaint.objects.filter(pk__in=[item.pk for item in self.complaints[3:]]).update(status=Complaint.Status.PENDING)
        keys = {badge.key for badge in resolve_user_badges(self.user)}
        self.assertNotIn("contributor", keys)
        self.assertNotIn("active-contributor", keys)
        self.assertIn("solution-focused", keys)

    def test_bulk_badge_resolution_has_constant_query_count(self):
        with CaptureQueriesContext(connection) as one:
            resolve_badges_for_users((self.user.pk,))
        ids = tuple(User.objects.filter(username__startswith="badge-helper-").values_list("pk", flat=True))
        with CaptureQueriesContext(connection) as many:
            resolve_badges_for_users((self.user.pk, *ids))
        self.assertEqual(len(one), len(many))
        self.assertLessEqual(len(many), 4)

    def test_badges_render_on_profile_and_only_one_on_public_detail(self):
        self.client.force_login(self.user)
        profile = self.client.get(reverse("accounts:profile"))
        self.assertContains(profile, "Rozetler")
        self.assertContains(profile, "Çözüm Odaklı")
        detail = self.client.get(reverse("complaints:public_detail", args=[self.complaints[0].pk]))
        self.assertEqual(detail.content.decode().count('class="public-user-badge"'), 2)
        public_comment = detail.context["comment_page"].object_list[0]
        self.assertNotIn("author_user", public_comment._state.fields_cache)
        self.assertNotContains(detail, self.user.email)


class ContactRequestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="contact-admin", email="admin-contact@example.com", password=PASSWORD, user_type="ADMIN", is_staff=True)
        cls.user = User.objects.create_user(username="contact-user", email="contact-user@example.com", password=PASSWORD, user_type="USER")

    def valid_data(self, **overrides):
        data = {"name": "Ada Yılmaz", "email": "ada@example.com", "request_type": "TECHNICAL", "subject": "Teknik destek", "message": "Form üzerinden iletilen güvenli destek mesajı."}
        data.update(overrides)
        return data

    def test_public_routes_valid_submit_and_database_record(self):
        self.assertEqual(self.client.get(reverse("core:about")).status_code, 200)
        self.assertEqual(self.client.get(reverse("core:contact")).status_code, 200)
        response = self.client.post(reverse("core:contact"), self.valid_data())
        self.assertRedirects(response, reverse("core:contact") + "?sent=1")
        item = ContactRequest.objects.get()
        self.assertEqual(item.status, ContactRequest.Status.NEW)
        self.assertEqual(item.request_type, ContactRequest.RequestType.TECHNICAL)
        self.assertContains(self.client.get(response["Location"]), "Mesajınız bize ulaştı")

    def test_contact_validation_csrf_and_xss_escaping(self):
        for data in (self.valid_data(email="invalid"), self.valid_data(subject=""), self.valid_data(message="")):
            self.assertEqual(self.client.post(reverse("core:contact"), data).status_code, 400)
        csrf_client = Client(enforce_csrf_checks=True)
        self.assertEqual(csrf_client.post(reverse("core:contact"), self.valid_data()).status_code, 403)
        attack = '<script>alert("stored")</script>'
        self.client.post(reverse("core:contact"), self.valid_data(message=attack))
        item = ContactRequest.objects.get()
        self.client.force_login(self.admin)
        detail = self.client.get(reverse("adminx:contact_detail", args=[item.pk]))
        self.assertContains(detail, "&lt;script&gt;", html=False)
        self.assertNotContains(detail, attack)

    def test_admin_authorization_detail_and_status_update(self):
        item = ContactRequest.objects.create(**self.valid_data())
        self.assertEqual(self.client.get(reverse("adminx:contact_list")).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("adminx:contact_detail", args=[item.pk])).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("adminx:contact_list")).status_code, 200)
        status_url = reverse("adminx:contact_status", args=[item.pk])
        self.assertEqual(self.client.get(status_url).status_code, 405)
        self.assertRedirects(self.client.post(status_url, {"status": "CLOSED"}), reverse("adminx:contact_detail", args=[item.pk]))
        item.refresh_from_db()
        self.assertEqual(item.status, ContactRequest.Status.CLOSED)
        self.client.post(status_url, {"status": "INJECTED"})
        item.refresh_from_db()
        self.assertEqual(item.status, ContactRequest.Status.CLOSED)
