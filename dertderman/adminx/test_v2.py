from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from blog.models import Post
from companies.models import Company, CompanyCategory, CompanyMembership, CompanyNotification
from complaints.models import Complaint


class AdminV2Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="v2-admin", email="v2-admin@example.com", user_type="ADMIN")
        cls.reader = User.objects.create_user(username="v2-reader", email="v2-reader@example.com")
        cls.agent = User.objects.create_user(username="v2-company", email="v2-company@example.com", user_type="COMPANY")
        cls.category = CompanyCategory.objects.create(name="İletişim")
        cls.companies = [Company.objects.create(name=f"V2 Şirket {i}", category=cls.category,
            email=f"company-{i}@example.com", is_verified=True, approval_status="PENDING") for i in range(13)]
        CompanyMembership.objects.create(company=cls.companies[0], user=cls.agent, role="OWNER")
        cls.complaints = [Complaint.objects.create(user=cls.reader, company=cls.companies[0],
            title=f"V2 Telefon {i}", description="İnceleme metni") for i in range(13)]
        cls.posts = [Post.objects.create(title=f"V2 Yazı {i}", excerpt="Özet", content="Metin",
            author=cls.admin, status="PUBLISHED", published_at=timezone.now()) for i in range(13)]
        cls.accounts = [User.objects.create_user(username=f"v2-account-{i}", email=f"account-{i}@example.com") for i in range(13)]
        tied = timezone.now()
        for model, ids, field in [(Company, cls.companies, "created_at"), (Complaint, cls.complaints, "created_at"),
                                   (Post, cls.posts, "created_at"), (User, cls.accounts, "date_joined")]:
            model.objects.filter(pk__in=[x.pk for x in ids]).update(**{field: tied})

    def setUp(self):
        self.client.force_login(self.admin)

    def test_admin_lists_are_complete_stable_and_five_per_page(self):
        cases = [("company_list", self.companies, {"q": "V2 Şirket"}),
                 ("company_application_list", self.companies, {"status": "PENDING"}),
                 ("complaint_list", self.complaints, {"q": "V2 Telefon"}),
                 ("blog_list", self.posts, {"status": "PUBLISHED"}),
                 ("user_list", self.accounts, {"q": "v2-account"})]
        for route, records, filters in cases:
            with self.subTest(route=route):
                seen = []
                for number, count in [(1, 5), (2, 5), (3, 3)]:
                    response = self.client.get(reverse(f"adminx:{route}"), {**filters, "page": number})
                    self.assertEqual(response.status_code, 200)
                    page = response.context["page_obj"]
                    self.assertEqual(len(page), count)
                    self.assertTemplateUsed(response, "components/pagination.html")
                    seen.extend(x.pk for x in page)
                self.assertEqual(seen, [x.pk for x in reversed(records)])
                self.assertEqual(len(seen), len(set(seen)))

    def test_invalid_pages_and_invalid_filters_never_raise(self):
        for route in ["company_list", "company_application_list", "complaint_list", "user_list", "blog_list", "notifications", "activity"]:
            for value in ["abc", "-5", "999999"]:
                with self.subTest(route=route, page=value):
                    self.assertEqual(self.client.get(reverse(f"adminx:{route}"), {"page": value}).status_code, 200)
        for route, parameter in [("company_list", "category"), ("complaint_list", "company"), ("user_list", "role"), ("blog_list", "status")]:
            response = self.client.get(reverse(f"adminx:{route}"), {parameter: "invalid"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["filter_form"].errors)
            self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_search_and_combined_filters_survive_page_links(self):
        params = {"s": "V2 Telefon", "status": "PENDING", "company": str(self.companies[0].pk), "page": 2}
        response = self.client.get(reverse("adminx:complaint_list"), params)
        self.assertEqual(response.context["page_obj"].paginator.count, 13)
        import re
        from html import unescape
        links = re.findall(r'href="([^\"]+)"', response.content.decode())
        queries = [parse_qs(urlsplit(unescape(link)).query) for link in links if "page=3" in link]
        self.assertTrue(queries)
        self.assertEqual(queries[0], {**{key: [value] for key, value in params.items() if key != "page"}, "page": ["3"]})
        response = self.client.get(reverse("adminx:company_list"), {"q": "V2", "category": self.category.pk,
            "verified": "1", "active": "1", "status": "PENDING", "page": 2})
        self.assertEqual(response.context["page_obj"].paginator.count, 13)
        self.assertEqual(len(response.context["page_obj"]), 5)
        response = self.client.get(reverse("adminx:user_list"), {"q": "v2-account", "role": "USER", "active": "0"})
        self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_all_statuses_can_be_selected_without_changing_moderation_default(self):
        Complaint.objects.filter(pk=self.complaints[0].pk).update(status="PUBLISHED")
        url = reverse("adminx:complaint_list")
        self.assertEqual(self.client.get(url).context["page_obj"].paginator.count, 12)
        response = self.client.get(url, {"status": "PUBLISHED"})
        self.assertEqual(list(response.context["page_obj"]), [self.complaints[0]])
        self.assertEqual(self.client.get(url, {"status": ""}).context["page_obj"].paginator.count, 13)

    def test_dashboard_counts_and_previews_are_real_and_bounded(self):
        CompanyNotification.objects.create(company=self.companies[0], kind="ADMIN", title="Yönetim işlemi")
        response = self.client.get(reverse("adminx:home"))
        for key in ["recent_complaints", "recent_applications", "recent_users", "recent_posts"]:
            self.assertEqual(len(response.context[key]), 5)
        self.assertEqual(response.context["user_count"], User.objects.count())
        self.assertEqual(response.context["company_count"], 13)
        self.assertEqual(response.context["pending_count"], 13)
        self.assertEqual(response.context["blog_count"], 13)
        self.assertEqual(response.context["activity_count"], CompanyNotification.objects.count())
        self.assertContains(response, "?status=PENDING")
        self.assertNotContains(response, 'class="dd-pagination"')

    def test_every_new_read_route_fails_closed_and_is_uncacheable(self):
        urls = [reverse(f"adminx:{route}") for route in ["home", "company_list", "company_application_list", "complaint_list", "user_list", "blog_list", "notifications", "activity", "homepage_content"]]
        urls += [reverse("adminx:user_detail", args=[self.reader.pk]), reverse("adminx:company_application_detail", args=[self.companies[0].pk])]
        for user in [self.reader, self.agent, self.admin]:
            self.client.force_login(user)
            for url in urls:
                response = self.client.get(url)
                with self.subTest(role=user.user_type, url=url):
                    self.assertEqual(response.status_code, 200 if user == self.admin else 403)
                    if user == self.admin:
                        self.assertIn("no-store", response["Cache-Control"])
        for url in ["/admin/", "/django-admin/"]:
            self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_account_detail_is_read_only_and_never_exposes_security_fields(self):
        url = reverse("adminx:user_detail", args=[self.reader.pk])
        response = self.client.get(url)
        self.assertIn("password", response.context["account"].get_deferred_fields())
        self.assertNotContains(response, self.reader.password)
        self.assertEqual(self.client.post(url, {"user_type": "ADMIN"}).status_code, 405)
        self.reader.refresh_from_db()
        self.assertEqual(self.reader.user_type, "USER")

    def test_blog_author_is_server_assigned_and_preserved_on_edit(self):
        data = {"title": "Yeni rehber", "excerpt": "Özet", "content": "Yazı içeriği", "author": self.reader.pk}
        response = self.client.post(reverse("adminx:blog_create"), data)
        self.assertEqual(response.status_code, 302)
        post = Post.objects.get(title=data["title"])
        self.assertEqual(post.author, self.admin)
        self.client.post(reverse("adminx:blog_edit", args=[post.pk]), data)
        self.client.post(reverse("adminx:blog_publish", args=[post.pk]))
        post.refresh_from_db()
        self.assertEqual(post.author, self.admin)
        self.assertEqual(post.status, "PUBLISHED")

    def test_activity_period_and_pagination(self):
        CompanyNotification.objects.all().delete()
        events = [CompanyNotification.objects.create(company=self.companies[0], kind="ADMIN", title=f"Olay {i}") for i in range(22)]
        CompanyNotification.objects.filter(pk=events[0].pk).update(created_at=timezone.now() - timedelta(days=8))
        response = self.client.get(reverse("adminx:activity"), {"period": "7", "page": 2})
        self.assertEqual(response.context["page_obj"].paginator.count, 21)
        self.assertEqual(len(response.context["page_obj"]), 5)
        self.assertContains(response, "period=7&amp;page=3")

    def test_shells_are_distinct_and_critical_buttons_request_confirmation(self):
        response = self.client.get(reverse("adminx:home"))
        self.assertTemplateUsed(response, "layouts/admin_base.html")
        self.assertNotContains(response, 'class="site-header"')
        self.assertContains(response, 'aria-current="page"')
        for route, pk in [("complaint_detail", self.complaints[0].pk), ("company_application_detail", self.companies[0].pk)]:
            response = self.client.get(reverse(f"adminx:{route}", args=[pk]))
            self.assertContains(response, "data-confirm=")
            self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.client.force_login(self.reader)
        self.assertTemplateUsed(self.client.get(reverse("dashboard:home")), "layouts/user_base.html")
        self.assertTemplateUsed(Client().get("/"), "layouts/public_base.html")
