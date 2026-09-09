from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from complaints.models import Complaint
from .models import Company, CompanyCategory, CompanyMembership, CompanyNotification, CompanyNotificationRead, CompanyResponse, InternalCompanyNote
from .panel_permissions import COMPANY_SESSION_KEY
from .panel_services import create_company_entry
from .services import active_company_memberships_for


User = get_user_model()


class CompanyPanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reader = User.objects.create_user(username="consumer-reader", email="reader@example.com")
        cls.owner = User.objects.create_user(username="owner-a", email="owner-a@example.com", user_type="COMPANY")
        cls.other_owner = User.objects.create_user(username="owner-b", email="owner-b@example.com", user_type="COMPANY")
        cls.manager = User.objects.create_user(username="manager-a", email="manager@example.com", user_type="COMPANY")
        cls.support = User.objects.create_user(username="support-a", email="support@example.com", user_type="COMPANY")
        cls.admin = User.objects.create_user(username="panel-admin", email="admin@example.com", user_type="ADMIN", is_staff=True, is_superuser=True)
        cls.a = Company.objects.create(name="Company Alpha", is_verified=True)
        cls.b = Company.objects.create(name="Company Beta", is_verified=True)
        cls.membership = CompanyMembership.objects.create(user=cls.owner, company=cls.a, role="OWNER")
        CompanyMembership.objects.create(user=cls.other_owner, company=cls.b, role="OWNER")
        CompanyMembership.objects.create(user=cls.manager, company=cls.a, role="MANAGER")
        CompanyMembership.objects.create(user=cls.support, company=cls.a, role="SUPPORT")
        cls.own = Complaint.objects.create(user=cls.reader, company=cls.a, title="Alpha teslimat sorunu", description="Alpha paket teslimat deneyimi ayrıntıları.", status="PUBLISHED")
        cls.pending = Complaint.objects.create(user=cls.reader, company=cls.a, title="Alpha bekleyen inceleme", description="İnceleme aşamasındaki deneyim ayrıntıları.")
        cls.resolved = Complaint.objects.create(user=cls.reader, company=cls.a, title="Alpha çözülmüş kayıt", description="Çözüme ulaşan deneyimin ayrıntıları.", status="RESOLVED")
        cls.foreign = Complaint.objects.create(user=cls.reader, company=cls.b, title="BETA PRIVATE COMPLAINT", description="BETA PRIVATE DESCRIPTION", status="PUBLISHED")

    def setUp(self):
        self.client.force_login(self.owner)

    def route(self, name, pk=None):
        return reverse(f"companies:{name}", args=[pk] if pk is not None else [])

    def all_get_urls(self):
        return [self.route(name) for name in ("company_panel", "complaint_list", "responses", "profile", "members", "notifications", "settings")] + [self.route("complaint_detail", self.own.pk), reverse("companies:company_panel_detail", args=[self.a.slug])]

    def mutation_urls(self, pk=None):
        return [self.route("response_create", pk or self.own.pk), self.route("note_create", pk or self.own.pk), self.route("profile"), self.route("switch_company"), self.route("notification_read", self.a.panel_notifications.first().pk)]

    def test_valid_company_can_open_all_pages_without_cache(self):
        for url in self.all_get_urls():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.a.name)
                self.assertIn("no-store", response.headers["Cache-Control"])
                self.assertNotContains(response, self.foreign.title)

    def test_user_and_admin_denied_on_every_direct_url_and_post(self):
        # Even a malformed membership and superuser flag never impersonate a company.
        for user in (self.reader, self.admin):
            CompanyMembership.objects.create(user=user, company=self.a, role="OWNER")
            self.client.force_login(user)
            for url in self.all_get_urls():
                with self.subTest(user=user.user_type, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 403)
                    self.assertIn("no-store", response.headers["Cache-Control"])
            for url in self.mutation_urls():
                with self.subTest(user=user.user_type, post=url):
                    self.assertEqual(self.client.post(url, {"body": "Unauthorized body", "name": "Changed"}).status_code, 403)
        self.assertFalse(CompanyResponse.objects.exists())
        self.assertFalse(InternalCompanyNote.objects.exists())

    def test_anonymous_panel_redirects_to_existing_login(self):
        self.client.logout()
        for url in self.all_get_urls():
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith(reverse("accounts:login")))

    def test_all_access_requirements_fail_closed(self):
        cases = [("membership", "is_active", False), ("membership", "role", "UNKNOWN"),
            ("company", "approval_status", "PENDING"), ("company", "approval_status", "REJECTED"),
            ("company", "is_active", False), ("company", "is_verified", False)]
        for model, field, value in cases:
            obj = self.membership if model == "membership" else self.a
            original = getattr(obj, field)
            type(obj).objects.filter(pk=obj.pk).update(**{field: value})
            try:
                for url in self.all_get_urls():
                    with self.subTest(model=model, field=field, value=value, url=url):
                        self.assertEqual(self.client.get(url).status_code, 403)
                for url in self.mutation_urls():
                    self.assertEqual(self.client.post(url, {"body": "Rejected action"}).status_code, 403)
            finally:
                type(obj).objects.filter(pk=obj.pk).update(**{field: original})

    def test_no_membership_and_inactive_user_are_denied(self):
        self.membership.delete()
        self.assertEqual(self.client.get(self.route("company_panel")).status_code, 403)
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        self.assertFalse(active_company_memberships_for(self.owner).exists())

    def test_cross_company_detail_response_and_note_are_404(self):
        for pk in (self.foreign.pk, 999999):
            with self.subTest(pk=pk):
                response = self.client.get(self.route("complaint_detail", pk))
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(response, self.foreign.title, status_code=404)
                for name in ("response_create", "note_create"):
                    response = self.client.post(self.route(name, pk), {"body": "Cross-company attack"})
                    self.assertEqual(response.status_code, 404)
                    self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertFalse(CompanyResponse.objects.exists())
        self.assertFalse(InternalCompanyNote.objects.exists())

    def test_response_and_note_attach_trusted_company_and_author(self):
        for name, model in (("response_create", CompanyResponse), ("note_create", InternalCompanyNote)):
            with self.subTest(name=name):
                response = self.client.post(self.route(name, self.own.pk), {
                    "body": "  Güvenli bir çözüm açıklaması.  ", "company": self.b.pk,
                    "author_user": self.other_owner.pk, "complaint": self.foreign.pk, "is_active": "false",
                })
                self.assertRedirects(response, self.route("complaint_detail", self.own.pk))
                entry = model.objects.get()
                self.assertEqual(entry.company_id, self.a.pk)
                self.assertEqual(entry.author_user_id, self.owner.pk)
                self.assertEqual(entry.complaint_id, self.own.pk)
                self.assertEqual(entry.body, "Güvenli bir çözüm açıklaması.")

    def test_empty_and_oversized_communication_is_rejected(self):
        for name, maximum, model in (("response_create", 5000, CompanyResponse), ("note_create", 3000, InternalCompanyNote)):
            for body in ("", " \t\n ", "x" * (maximum + 1)):
                with self.subTest(name=name, size=len(body)):
                    response = self.client.post(self.route(name, self.own.pk), {"body": body})
                    self.assertEqual(response.status_code, 400)
                    self.assertFalse(model.objects.exists())
            self.assertEqual(self.client.post(self.route(name, self.own.pk), {"body": "x" * maximum}).status_code, 302)

    def test_service_and_model_validate_ownership_and_access(self):
        with self.assertRaises(PermissionDenied):
            create_company_entry(user=self.reader, company_id=self.a.pk, complaint_id=self.own.pk, body="No authority")
        for model in (CompanyResponse, InternalCompanyNote):
            with self.assertRaises(ValidationError):
                model.objects.create(company=self.a, complaint=self.foreign, author_user=self.owner, body="Wrong ownership")
            with self.assertRaises(ValidationError):
                model.objects.create(company=self.a, complaint=self.own, author_user=self.owner, body="   ")

    def test_internal_notes_never_reach_public_or_another_company(self):
        note = InternalCompanyNote.objects.create(company=self.a, complaint=self.own, author_user=self.owner, body="CONFIDENTIAL INTERNAL ALPHA NOTE")
        reply = CompanyResponse.objects.create(company=self.a, complaint=self.own, author_user=self.owner, body="PUBLIC ALPHA RESPONSE")
        private = self.client.get(self.route("complaint_detail", self.own.pk))
        self.assertContains(private, note.body)
        self.assertNotContains(self.client.get(self.route("responses")), note.body)
        self.client.force_login(self.other_owner)
        for url in (self.route("company_panel"), self.route("responses"), self.route("notifications"), self.route("complaint_detail", self.foreign.pk)):
            self.assertNotContains(self.client.get(url), note.body)
        self.client.logout()
        public = self.client.get(reverse("complaints:public_detail", args=[self.own.pk]))
        self.assertContains(public, reply.body)
        self.assertNotContains(public, note.body)
        self.assertNotIn("notes", public.context)

    def test_public_responses_respect_publication_and_active_flag(self):
        reply = CompanyResponse.objects.create(company=self.a, complaint=self.own, author_user=self.owner, body="ACTIVE PUBLIC RESPONSE")
        url = reverse("complaints:public_detail", args=[self.own.pk])
        for status in ("PENDING", "REJECTED", "RESOLVED"):
            Complaint.objects.filter(pk=self.own.pk).update(status=status)
            self.assertEqual(self.client.get(url).status_code, 404)
        Complaint.objects.filter(pk=self.own.pk).update(status="PUBLISHED")
        CompanyResponse.objects.filter(pk=reply.pk).update(is_active=False)
        self.assertNotContains(self.client.get(url), reply.body)
        Company.objects.filter(pk=self.a.pk).update(is_active=False)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_response_and_note_xss_is_escaped(self):
        attack = '<script>alert("panel-xss")</script>'
        self.client.post(self.route("response_create", self.own.pk), {"body": attack})
        self.client.post(self.route("note_create", self.own.pk), {"body": attack})
        for url in (self.route("complaint_detail", self.own.pk), self.route("responses"), reverse("complaints:public_detail", args=[self.own.pk])):
            response = self.client.get(url)
            self.assertNotContains(response, attack)
            self.assertContains(response, "&lt;script&gt;")

    def test_roles_enforced_for_get_and_post(self):
        for user, can_manage in ((self.support, False), (self.manager, True), (self.owner, True)):
            self.client.force_login(user)
            with self.subTest(role=user.username):
                self.assertEqual(self.client.get(self.route("complaint_detail", self.own.pk)).status_code, 200)
                self.assertEqual(self.client.get(self.route("profile")).status_code, 200)
                self.assertEqual(self.client.get(self.route("members")).status_code, 200 if can_manage else 403)
                for name in ("response_create", "note_create"):
                    self.assertEqual(self.client.post(self.route(name, self.own.pk), {"body": f"Entry by {user.username}"}).status_code, 302)
                self.assertEqual(self.client.post(self.route("profile"), {"name": "Managed Company"}).status_code, 302 if can_manage else 403)
                self.assertEqual(self.client.post(self.route("members"), {"role": "OWNER", "user": user.pk}).status_code, 405)

    def test_profile_whitelist_cannot_change_privileges_or_other_company(self):
        response = self.client.post(self.route("profile"), {"name": "Updated Alpha", "description": "Public company description",
            "email": "public-contact@example.com", "website": "https://example.com", "phone": "5551234567",
            "company": self.b.pk, "id": self.b.pk, "slug": self.b.slug, "approval_status": "REJECTED",
            "is_active": "false", "is_verified": "false", "ownership": self.other_owner.pk, "role": "OWNER"})
        self.assertRedirects(response, self.route("profile"))
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.owner.refresh_from_db()
        self.assertEqual(self.a.name, "Updated Alpha")
        self.assertEqual(self.b.name, "Company Beta")
        self.assertTrue(self.a.is_active and self.a.is_verified)
        self.assertEqual(self.a.approval_status, "APPROVED")
        self.assertEqual(self.a.slug, "company-alpha")
        self.assertEqual(self.owner.email, "owner-a@example.com")

    def test_profile_rejects_unsafe_url_inactive_category_and_long_description(self):
        inactive = CompanyCategory.objects.create(name="Hidden category", is_active=False)
        for fields in ({"website": "javascript:alert(1)"}, {"category": inactive.pk}, {"description": "x" * 5001}):
            response = self.client.post(self.route("profile"), {"name": "Invalid update", **fields})
            self.assertEqual(response.status_code, 400)
            self.a.refresh_from_db()
            self.assertEqual(self.a.name, "Company Alpha")

    def test_csrf_required_for_all_mutations(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        for url in self.mutation_urls():
            self.assertEqual(csrf_client.post(url, {"body": "No CSRF", "name": "No CSRF"}).status_code, 403)
        self.assertFalse(CompanyResponse.objects.exists())
        csrf_client.get(self.route("complaint_detail", self.own.pk))
        token = csrf_client.cookies["csrftoken"].value
        self.assertEqual(csrf_client.post(self.route("response_create", self.own.pk), {"body": "Valid CSRF", "csrfmiddlewaretoken": token}).status_code, 302)

    def test_mutations_are_post_only_and_redirect_is_fixed(self):
        for name in ("response_create", "note_create"):
            self.assertEqual(self.client.get(self.route(name, self.own.pk)).status_code, 405)
            response = self.client.post(self.route(name, self.own.pk) + "?next=https://evil.example", {"body": "Safe redirect", "next": "https://evil.example"})
            self.assertEqual(response.url, self.route("complaint_detail", self.own.pk))
        for name in ("members", "responses", "settings", "notifications", "complaint_list"):
            self.assertEqual(self.client.post(self.route(name), {}).status_code, 405)

    def test_search_filters_and_pagination_stay_in_company(self):
        CompanyResponse.objects.create(company=self.a, complaint=self.own, author_user=self.owner, body="Reply")
        for state, expected in (("waiting", [self.pending.pk]), ("answered", [self.own.pk]), ("resolved", [self.resolved.pk])):
            response = self.client.get(self.route("complaint_list"), {"state": state})
            self.assertEqual([x.pk for x in response.context["page_obj"]], expected)
        self.assertEqual(self.client.get(self.route("complaint_list"), {"q": "BETA"}).context["page_obj"].paginator.count, 0)
        self.assertEqual(self.client.get(self.route("complaint_list"), {"q": "paket"}).context["page_obj"].paginator.count, 1)
        invalid = self.client.get(self.route("complaint_list"), {"start": "2026-10-01", "end": "2026-09-01"})
        self.assertTrue(invalid.context["filter_form"].errors)
        self.assertEqual(invalid.context["page_obj"].paginator.count, 0)
        for i in range(15):
            Complaint.objects.create(user=self.reader, company=self.a, title=f"Page item {i}", description="Pagination content.")
        first = self.client.get(self.route("complaint_list"), {"q": "Page", "page": 1})
        second = self.client.get(self.route("complaint_list"), {"q": "Page", "page": 2})
        self.assertEqual(len(first.context["page_obj"]), 6)
        self.assertEqual(len(second.context["page_obj"]), 6)
        self.assertContains(first, "q=Page&amp;page=2")

    def test_metrics_count_complaints_not_replies_and_average_first_response(self):
        created = timezone.now() - timedelta(hours=4)
        Complaint.objects.filter(pk=self.own.pk).update(created_at=created)
        first = CompanyResponse.objects.create(company=self.a, complaint=self.own, author_user=self.owner, body="First reply")
        second = CompanyResponse.objects.create(company=self.a, complaint=self.own, author_user=self.owner, body="Second reply")
        CompanyResponse.objects.filter(pk=first.pk).update(created_at=created + timedelta(hours=2))
        CompanyResponse.objects.filter(pk=second.pk).update(created_at=created + timedelta(hours=3))
        response = self.client.get(self.route("company_panel"))
        stats = response.context["metrics"]
        self.assertEqual((stats["total"], stats["waiting"], stats["answered"], stats["resolved"]), (3, 1, 1, 1))
        self.assertEqual(stats["average_response"], timedelta(hours=2))
        self.assertEqual(response.context["average_label"], "2.0 sa")

    def test_notifications_are_scoped_and_read_status_is_personal(self):
        notification = self.a.panel_notifications.first()
        foreign = self.b.panel_notifications.first()
        self.assertEqual(self.client.post(self.route("notification_read", foreign.pk)).status_code, 404)
        response = self.client.post(self.route("notification_read", notification.pk), {"user": self.manager.pk})
        self.assertRedirects(response, self.route("notifications"))
        self.assertTrue(CompanyNotificationRead.objects.filter(notification=notification, user=self.owner).exists())
        self.assertFalse(CompanyNotificationRead.objects.filter(notification=notification, user=self.manager).exists())
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(self.route("notifications")).context["unread_count"], 3)
        self.assertNotContains(self.client.get(self.route("notifications")), self.foreign.title)

    def test_company_selection_checks_membership_and_ignores_external_next(self):
        self.assertEqual(self.client.post(self.route("switch_company"), {"company_id": self.b.pk}).status_code, 404)
        CompanyMembership.objects.create(user=self.owner, company=self.b, role="SUPPORT")
        response = self.client.post(self.route("switch_company"), {"company_id": self.b.pk, "next": "https://evil.example"})
        self.assertEqual(response.url, self.route("company_panel"))
        self.assertEqual(self.client.session[COMPANY_SESSION_KEY], self.b.pk)
        self.assertEqual(self.client.get(self.route("complaint_detail", self.foreign.pk)).status_code, 200)
        self.assertEqual(self.client.get(self.route("complaint_detail", self.own.pk)).status_code, 404)
        self.assertEqual(self.client.post(self.route("profile"), {"name": "Support escalation"}).status_code, 403)

    def test_complaint_and_moderation_events_create_notifications_once(self):
        self.assertEqual(self.own.company_notifications.filter(kind="NEW").count(), 1)
        self.own.status = "RESOLVED"
        self.own.save(update_fields=["status", "updated_at"])
        self.assertEqual(self.own.company_notifications.filter(kind="RESOLVED").count(), 1)
        self.own.description = "Updated consumer details with a follow-up."
        self.own.save(update_fields=["description", "updated_at"])
        self.assertEqual(self.own.company_notifications.filter(kind="UPDATED").count(), 1)
        self.client.force_login(self.admin)
        url = reverse("adminx:complaint_publish", args=[self.pending.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self.pending.company_notifications.filter(kind="PUBLISHED").count(), 1)
        self.assertEqual(self.client.post(url).status_code, 409)
        self.assertEqual(self.pending.company_notifications.filter(kind="PUBLISHED").count(), 1)
