from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from companies.models import Company, CompanyMembership
from core.presentation import HERO_BRAND_MESSAGES


class ContentManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {role: get_user_model().objects.create_user(username=f"content-{role}", email=f"{role}@example.com", user_type=role) for role in ["ADMIN", "USER", "COMPANY", "UNKNOWN"]}
        cls.company = Company.objects.create(name="Managed company", is_active=False)

    def setUp(self):
        self.urls = [reverse(f"adminx:{name}") for name in ["company_list", "user_list", "homepage_content"]]
        self.edit_url = reverse("adminx:company_edit", args=[self.company.pk])
        self.urls.append(self.edit_url)

    def test_all_new_routes_require_admin_and_keep_no_store(self):
        for role in [None, *self.users]:
            client = Client()
            if role:
                client.force_login(self.users[role])
            for url in self.urls:
                with self.subTest(role=role, url=url):
                    response = client.get(url)
                    if role is None:
                        self.assertRedirects(response, f"/yonetim/giris/?next={url}")
                    else:
                        self.assertEqual(response.status_code, 200 if role == "ADMIN" else 403)
                    if role == "ADMIN":
                        self.assertIn("no-store", response["Cache-Control"])
                    else:
                        self.assertNotContains(response, self.company.name, status_code=response.status_code)
            if role != "ADMIN":
                response = client.post(self.edit_url, {"name": "Unauthorized change"})
                self.assertEqual(response.status_code, 302 if role is None else 403)
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Managed company")

    def test_company_edit_csrf_allowlist_and_missing_object(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.users["ADMIN"])
        data = {"name": "Updated company", "description": "Updated description", "website": "https://example.com", "email": "company@example.com", "phone": "123", "is_active": "true", "is_verified": "true", "slug": "tampered", "user_type": "ADMIN"}
        self.assertEqual(client.post(self.edit_url, data).status_code, 403)
        client.get(self.edit_url)
        slug = self.company.slug
        response = client.post(self.edit_url, data, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertRedirects(response, self.edit_url)
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Updated company")
        self.assertEqual(self.company.description, "Updated description")
        self.assertEqual(self.company.slug, slug)
        self.assertFalse(self.company.is_active)
        self.assertFalse(self.company.is_verified)
        self.assertEqual(CompanyMembership.objects.count(), 0)
        self.assertEqual(client.get(reverse("adminx:company_edit", args=[999999])).status_code, 404)

    def test_read_only_lists_and_pagination(self):
        self.client.force_login(self.users["ADMIN"])
        for url in self.urls[:-1]:
            self.assertEqual(self.client.post(url, {}).status_code, 405)
        Company.objects.bulk_create([Company(name=f"Page company {i}", slug=f"page-company-{i}") for i in range(22)])
        response = self.client.get(reverse("adminx:company_list"))
        self.assertEqual(len(response.context["page_obj"]), 20)
        self.assertEqual(response.context["page_obj"].paginator.count, 23)
        self.assertEqual(len(self.client.get(reverse("adminx:company_list") + "?page=2").context["page_obj"]), 3)
        response = self.client.get(reverse("adminx:user_list"))
        self.assertNotContains(response, self.users["ADMIN"].password)

    def test_brand_messages_share_source_and_management_links_resolve(self):
        response = self.client.get("/")
        for message in HERO_BRAND_MESSAGES:
            self.assertContains(response, message)
        self.assertContains(response, 'class="hero-brand"')
        self.assertNotContains(response, 'class="hero-visual-caption"')
        self.client.force_login(self.users["ADMIN"])
        response = self.client.get(reverse("adminx:homepage_content"))
        self.assertEqual(response.context["hero_brand_messages"], HERO_BRAND_MESSAGES)
        response = self.client.get(reverse("adminx:home"))
        for url in self.urls[:-1]:
            self.assertContains(response, f'href="{url}"')

    def test_logout_invalidates_new_management_pages(self):
        self.client.force_login(self.users["ADMIN"])
        old_session = self.client.cookies["sessionid"].value
        self.assertEqual(self.client.get("/hesap/cikis/").status_code, 405)
        self.client.post("/hesap/cikis/")
        self.client.cookies["sessionid"] = old_session
        for url in self.urls:
            self.assertRedirects(self.client.get(url), f"/yonetim/giris/?next={url}")
        response = self.client.get("/django-admin/")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
