import re

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from companies.models import Company
from complaints.models import Complaint


User = get_user_model()


class ComplaintModerationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="moderator", email="moderator@example.com", user_type=User.UserType.ADMIN
        )
        cls.owner = User.objects.create_user(
            username="complaint-owner", email="private-owner@example.com",
            phone="+905551234567", password="OwnerSecret2026!", user_type=User.UserType.USER,
        )
        cls.company_user = User.objects.create_user(
            username="company-reviewer", email="company-reviewer@example.com",
            user_type=User.UserType.COMPANY,
        )
        cls.company = Company.objects.create(name="Moderation Company")
        cls.records = {
            status: Complaint.objects.create(
                user=cls.owner, company=cls.company, status=status,
                title=f"Moderation complaint {status}",
                description=f"Complaint description for moderation: {status}.",
            ) for status in Complaint.Status.values
        }

    def setUp(self):
        self.client.force_login(self.admin)
        self.pending = self.records[Complaint.Status.PENDING]
        self.home_url = reverse("adminx:home")
        self.list_url = reverse("adminx:complaint_list")
        self.detail_url = reverse("adminx:complaint_detail", args=[self.pending.pk])

    def action_url(self, action, complaint=None):
        return reverse(f"adminx:complaint_{action}", args=[(complaint or self.pending).pk])

    def assert_no_store(self, response):
        directives = set(response["Cache-Control"].split(", "))
        self.assertTrue({"no-store", "no-cache", "private", "max-age=0", "must-revalidate"} <= directives)
        self.assertIn("Expires", response.headers)

    def test_pending_list_order_count_and_minimal_user_information(self):
        latest = Complaint.objects.create(
            user=self.owner, company=self.company, title="Newest pending complaint",
            description="New complaint for the moderation list.",
        )
        Complaint.objects.filter(pk__in=[self.pending.pk, latest.pk]).update(created_at=timezone.now())
        response = self.client.get(self.list_url)
        self.assertEqual(list(response.context["complaints"]), [latest, self.pending])
        for text in [latest.title, self.pending.title, self.company.name, self.owner.username,
                     "İncele", "Oluşturulma tarihi", "İncelemede", self.detail_url]:
            self.assertContains(response, text)
        for status in [Complaint.Status.PUBLISHED, Complaint.Status.REJECTED, Complaint.Status.RESOLVED]:
            self.assertNotContains(response, self.records[status].title)
        home = self.client.get(self.home_url)
        self.assertEqual(home.context["pending_count"], 2)
        self.assertContains(home, f'href="{self.list_url}"')
        for url in [self.list_url, self.detail_url]:
            response = self.client.get(url)
            for secret in [self.owner.email, self.owner.phone, self.owner.password,
                           "OwnerSecret2026!", self.client.session.session_key]:
                self.assertNotContains(response, secret)
        detail = self.client.get(self.detail_url).context["complaint"]
        self.assertIn("password", detail.user.get_deferred_fields())

    def test_admin_can_inspect_all_statuses_but_only_pending_has_actions(self):
        for status, complaint in self.records.items():
            with self.subTest(status=status):
                response = self.client.get(reverse("adminx:complaint_detail", args=[complaint.pk]))
                for text in [complaint.title, complaint.description, self.company.name,
                             self.owner.username, complaint.get_status_display(), "Son güncelleme"]:
                    self.assertContains(response, text)
                for action in ["publish", "reject"]:
                    form_action = f'action="{self.action_url(action, complaint)}"'
                    if status == Complaint.Status.PENDING:
                        self.assertContains(response, form_action)
                    else:
                        self.assertNotContains(response, form_action)

    def test_non_admins_are_denied_on_every_endpoint_including_owned_complaints(self):
        for user in [self.owner, self.company_user]:
            self.client.force_login(user)
            for url in [self.home_url, self.list_url, self.detail_url]:
                with self.subTest(user=user.username, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
            for action in ["publish", "reject"]:
                self.assertEqual(self.client.post(self.action_url(action)).status_code, 403)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Complaint.Status.PENDING)

    def test_staff_and_superuser_flags_do_not_replace_admin_role(self):
        self.owner.is_staff = True
        self.owner.is_superuser = True
        self.owner.save()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.detail_url).status_code, 403)
        self.assertEqual(self.client.post(self.action_url("publish")).status_code, 403)

    def test_anonymous_and_logged_out_admin_cannot_reuse_moderation_session(self):
        old_session = self.client.cookies["sessionid"].value
        for url in [self.home_url, self.list_url, self.detail_url]:
            self.assert_no_store(self.client.get(url))
        self.client.post(reverse("accounts:logout"))
        for replay_old_session in [False, True]:
            if replay_old_session:
                self.client.cookies["sessionid"] = old_session
            for url in [self.home_url, self.list_url, self.detail_url]:
                response = self.client.get(url)
                self.assertRedirects(response, f"{reverse('adminx:login')}?next={url}")
                self.assertNotContains(response, self.pending.title, status_code=302)
                self.assert_no_store(response)
            for action in ["publish", "reject"]:
                url = self.action_url(action)
                self.assertRedirects(self.client.post(url), f"{reverse('adminx:login')}?next={url}")
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Complaint.Status.PENDING)

    def test_actions_require_post_and_read_pages_cannot_mutate(self):
        for action in ["publish", "reject"]:
            for method in ["get", "head", "put", "patch", "delete"]:
                response = getattr(self.client, method)(self.action_url(action))
                self.assertEqual(response.status_code, 405)
                self.assert_no_store(response)
        for url in [self.home_url, self.list_url, self.detail_url]:
            self.assertEqual(self.client.post(url, {"status": "PUBLISHED"}).status_code, 405)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Complaint.Status.PENDING)

    def test_csrf_is_required_and_rendered_token_allows_each_action(self):
        for action, expected in [("publish", Complaint.Status.PUBLISHED), ("reject", Complaint.Status.REJECTED)]:
            with self.subTest(action=action):
                complaint = Complaint.objects.create(
                    user=self.owner, company=self.company, title=f"CSRF {action} complaint",
                    description="A complaint to verify CSRF enforcement.",
                )
                client = Client(enforce_csrf_checks=True)
                client.force_login(self.admin)
                url = self.action_url(action, complaint)
                self.assertEqual(client.post(url).status_code, 403)
                complaint.refresh_from_db()
                self.assertEqual(complaint.status, Complaint.Status.PENDING)
                detail = client.get(reverse("adminx:complaint_detail", args=[complaint.pk]))
                token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', detail.content.decode()).group(1)
                self.assertEqual(client.post(url, {"csrfmiddlewaretoken": token}).status_code, 302)
                complaint.refresh_from_db()
                self.assertEqual(complaint.status, expected)

    def test_invalid_transitions_return_409_without_changes(self):
        for status in [Complaint.Status.PUBLISHED, Complaint.Status.REJECTED, Complaint.Status.RESOLVED]:
            complaint = self.records[status]
            original_updated_at = complaint.updated_at
            for action in ["publish", "reject"]:
                with self.subTest(status=status, action=action):
                    response = self.client.post(self.action_url(action, complaint))
                    self.assertEqual(response.status_code, 409)
                    self.assertContains(response, "Karar uygulanmadı.", status_code=409)
                    self.assert_no_store(response)
                    complaint.refresh_from_db()
                    self.assertEqual(complaint.status, status)
                    self.assertEqual(complaint.updated_at, original_updated_at)

    def test_stale_review_and_double_submit_cannot_overwrite_first_decision(self):
        second_client = Client()
        second_client.force_login(self.admin)
        self.assertEqual(second_client.get(self.detail_url).status_code, 200)
        self.assertEqual(self.client.post(self.action_url("publish")).status_code, 302)
        self.pending.refresh_from_db()
        published_at = self.pending.updated_at
        for action in ["publish", "reject"]:
            self.assertEqual(second_client.post(self.action_url(action)).status_code, 409)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Complaint.Status.PUBLISHED)
        self.assertEqual(self.pending.updated_at, published_at)

    def test_client_cannot_choose_status_or_change_other_fields(self):
        old_updated_at = self.pending.updated_at
        response = self.client.post(self.action_url("reject"), {
            "status": Complaint.Status.PUBLISHED, "user": self.admin.pk,
            "title": "Tampered title", "company": 999999,
        })
        self.assertRedirects(response, self.detail_url)
        self.assert_no_store(response)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Complaint.Status.REJECTED)
        self.assertEqual(self.pending.user_id, self.owner.pk)
        self.assertEqual(self.pending.company_id, self.company.pk)
        self.assertEqual(self.pending.title, "Moderation complaint PENDING")
        self.assertGreater(self.pending.updated_at, old_updated_at)

    def test_missing_complaint_returns_404(self):
        for name in ["complaint_detail", "complaint_publish", "complaint_reject"]:
            url = reverse(f"adminx:{name}", args=[999999])
            method = self.client.get if name == "complaint_detail" else self.client.post
            self.assertEqual(method(url).status_code, 404)

    def test_stored_xss_is_escaped_in_admin_list_and_detail(self):
        self.pending.title = '<script>alert(1)</script>'
        self.pending.description = '<img src=x onerror="alert(2)">\n<script>alert(3)</script>'
        self.pending.save()
        for url in [self.list_url, self.detail_url]:
            response = self.client.get(url)
            self.assertContains(response, escape(self.pending.title))
            self.assertNotContains(response, self.pending.title)
        self.assertContains(response, escape(self.pending.description))
        self.assertNotContains(response, self.pending.description)

    def _create_and_moderate(self, action, expected):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("complaints:create"), {
            "company": self.company.pk, "title": f"End-to-end {action} complaint",
            "description": "A real creation request followed by an admin moderation decision.",
        })
        self.assertRedirects(response, reverse("dashboard:home"))
        complaint = Complaint.objects.get(title=f"End-to-end {action} complaint")
        self.assertEqual(complaint.status, Complaint.Status.PENDING)
        public = Client()
        public_detail = reverse("complaints:public_detail", args=[complaint.pk])
        public_pages = [reverse("complaints:public_list"), reverse("core:home")]
        for url in public_pages:
            self.assertNotContains(public.get(url), complaint.title)
        self.assertEqual(public.get(public_detail).status_code, 404)
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.post(self.action_url(action, complaint)),
                             reverse("adminx:complaint_detail", args=[complaint.pk]))
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, expected)
        for url in public_pages:
            response = public.get(url)
            if expected == Complaint.Status.PUBLISHED:
                self.assertContains(response, complaint.title)
            else:
                self.assertNotContains(response, complaint.title)
        self.assertEqual(public.get(public_detail).status_code,
                         200 if expected == Complaint.Status.PUBLISHED else 404)
        self.assertNotContains(self.client.get(self.list_url), complaint.title)
        self.client.force_login(self.owner)
        for url in [reverse("complaints:list"), reverse("complaints:detail", args=[complaint.pk])]:
            response = self.client.get(url)
            self.assertContains(response, complaint.title)
            self.assertContains(response, complaint.get_status_display())
            self.assert_no_store(response)

    def test_user_creation_admin_publish_public_and_private_integration(self):
        self._create_and_moderate("publish", Complaint.Status.PUBLISHED)

    def test_user_creation_admin_reject_public_and_private_integration(self):
        self._create_and_moderate("reject", Complaint.Status.REJECTED)

    def test_empty_moderation_list(self):
        self.client.post(self.action_url("reject"))
        self.assertContains(self.client.get(self.list_url), "İnceleme bekleyen şikayet bulunmuyor.")
        self.assertEqual(self.client.get(self.home_url).context["pending_count"], 0)

    def test_publish_preserves_existing_inactive_company_public_policy(self):
        self.company.is_active = False
        self.company.save()
        self.assertContains(self.client.get(self.list_url), self.pending.title)
        self.assertEqual(self.client.post(self.action_url("publish")).status_code, 302)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Complaint.Status.PUBLISHED)
        public = Client()
        for url in [reverse("complaints:public_list"), reverse("core:home")]:
            self.assertNotContains(public.get(url), self.pending.title)
        self.assertEqual(public.get(reverse("complaints:public_detail", args=[self.pending.pk])).status_code, 404)
