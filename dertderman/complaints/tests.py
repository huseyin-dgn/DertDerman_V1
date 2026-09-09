from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils.html import escape

from companies.models import Company

from .models import Complaint


User = get_user_model()


class PrivateComplaintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="private-owner", email="private-owner@example.com", user_type="USER"
        )
        cls.other = User.objects.create_user(
            username="private-other", email="private-other@example.com", user_type="USER"
        )
        cls.company = Company.objects.create(name="Private Test Company")
        cls.owned = [
            Complaint.objects.create(
                user=cls.owner,
                company=cls.company,
                title=f"Owner complaint {status}",
                description=f"Private description for {status} complaint.",
                status=status,
            )
            for status in Complaint.Status.values
        ]
        cls.foreign = Complaint.objects.create(
            user=cls.other,
            company=cls.company,
            title="Other user's secret title",
            description="Other user's secret description.",
        )

    def setUp(self):
        self.client.force_login(self.owner)
        self.list_url = reverse("complaints:list")
        self.detail_url = reverse("complaints:detail", args=[self.owned[0].pk])

    def test_list_is_owner_scoped_and_newest_first(self):
        response = self.client.get(self.list_url, {"user": self.other.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["complaints"]), list(reversed(self.owned)))
        self.assertNotContains(response, escape(self.foreign.title))
        for complaint in self.owned:
            self.assertContains(response, complaint.title)
            self.assertContains(response, complaint.get_status_display())
            self.assertContains(response, reverse("complaints:detail", args=[complaint.pk]))

    def test_empty_state_has_create_action(self):
        empty_user = User.objects.create_user(
            username="empty-owner", email="empty-owner@example.com", user_type="USER"
        )
        self.client.force_login(empty_user)
        response = self.client.get(self.list_url)
        self.assertContains(response, "Henüz bir şikayetiniz bulunmuyor.")
        self.assertContains(response, reverse("complaints:create"))

    def test_owner_can_view_every_status_including_pending(self):
        for complaint in self.owned:
            with self.subTest(status=complaint.status):
                response = self.client.get(reverse("complaints:detail", args=[complaint.pk]))
                self.assertEqual(response.context["complaint"], complaint)
                for content in [complaint.title, complaint.description, self.company.name,
                                complaint.get_status_display(), "Oluşturulma tarihi",
                                "Son güncelleme tarihi", "Şikayetlerime Dön"]:
                    self.assertContains(response, content)
                if complaint.status == Complaint.Status.PENDING:
                    self.assertContains(response, "Henüz yayınlanmadı.")

    def test_other_user_cannot_read_owner_complaint_by_id(self):
        self.client.force_login(self.other)
        for complaint in self.owned:
            with self.subTest(status=complaint.status):
                response = self.client.get(reverse("complaints:detail", args=[complaint.pk]))
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(response, complaint.title, status_code=404)
                self.assertNotContains(response, complaint.description, status_code=404)
                self.assertNotContains(response, self.company.name, status_code=404)

    def test_nonexistent_id_returns_404(self):
        response = self.client.get(reverse("complaints:detail", args=[999999]))
        self.assertEqual(response.status_code, 404)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        for url in [self.list_url, self.detail_url]:
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), f"{reverse('accounts:login')}?next={url}")

    def test_company_and_admin_are_forbidden_even_for_owned_objects(self):
        for role in [User.UserType.COMPANY, User.UserType.ADMIN]:
            user = User.objects.create_user(
                username=f"private-{role}", email=f"private-{role}@example.com", user_type=role
            )
            complaint = Complaint.objects.create(
                user=user, company=self.company, title="Role-owned complaint",
                description="This object must still be inaccessible.",
            )
            self.client.force_login(user)
            for url in [self.list_url, self.detail_url,
                        reverse("complaints:detail", args=[complaint.pk])]:
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_user_content_is_escaped(self):
        complaint = self.owned[0]
        complaint.title = '<script>alert(1)</script>'
        complaint.description = '<img src=x onerror="alert(2)">\n<script>alert(3)</script>'
        complaint.save()
        for url in [self.list_url, self.detail_url]:
            response = self.client.get(url)
            self.assertContains(response, escape(complaint.title))
            self.assertNotContains(response, complaint.title)
        self.assertContains(response, escape(complaint.description))
        self.assertNotContains(response, complaint.description)

    def test_private_responses_are_not_cacheable(self):
        for url in [self.list_url, self.detail_url]:
            with self.subTest(url=url):
                response = self.client.get(url)
                directives = {part.strip() for part in response["Cache-Control"].split(",")}
                self.assertTrue({"no-store", "no-cache", "private", "max-age=0", "must-revalidate"} <= directives)
                self.assertIn("Expires", response.headers)
                self.assertNotContains(response, "js/private-page.js")

    def test_logout_blocks_both_private_urls(self):
        for url in [self.list_url, self.detail_url]:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertRedirects(self.client.post(reverse("accounts:logout")), reverse("core:home"))
        for url in [self.list_url, self.detail_url]:
            response = self.client.get(url)
            self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")
            self.assertNotIn(self.owned[0].title, response.content.decode())

    def test_private_views_reject_mutation_methods(self):
        for url in [self.list_url, self.detail_url]:
            for method in ["post", "put", "patch", "delete"]:
                with self.subTest(url=url, method=method):
                    response = getattr(self.client, method)(url, {"status": "PUBLISHED"})
                    self.assertEqual(response.status_code, 405)
        self.owned[0].refresh_from_db()
        self.assertEqual(self.owned[0].status, Complaint.Status.PENDING)
        self.assertEqual(Complaint.objects.count(), 5)

    def test_panel_keeps_three_recent_complaints_and_private_links(self):
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(list(response.context["recent_complaints"]), list(reversed(self.owned))[:3])
        self.assertContains(response, reverse("complaints:list"))
        self.assertContains(response, "Tüm Şikayetlerimi Gör")
        for complaint in self.owned[1:]:
            self.assertContains(response, reverse("complaints:detail", args=[complaint.pk]))
        self.assertNotContains(response, self.owned[0].title)
        self.assertNotContains(response, escape(self.foreign.title))


class PublicComplaintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username="secret-public-owner", email="secret-owner@example.com",
            phone="+905559876543", first_name="PrivateFirstName",
            last_name="PrivateLastName", user_type=User.UserType.USER,
        )
        cls.company = Company.objects.create(name="Public Company")
        cls.complaints = {
            status: Complaint.objects.create(
                user=cls.owner, company=cls.company, status=status,
                title=f"Unique complaint {status}",
                description=f"Unique description {status}. " + "Long preview text. " * 30,
            )
            for status in Complaint.Status.values
        }
        cls.published = cls.complaints[Complaint.Status.PUBLISHED]

    def setUp(self):
        self.list_url = reverse("complaints:public_list")
        self.detail_url = reverse("complaints:public_detail", args=[self.published.pk])
        self.home_url = reverse("core:home")

    def test_anonymous_list_and_home_only_show_published(self):
        for url in [self.list_url, self.home_url]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, self.published.title)
                self.assertContains(response, self.detail_url)
                self.assertContains(response, self.company.name)
                self.assertContains(response, self.published.get_status_display())
                self.assertContains(response, self.published.description[:100])
                self.assertNotContains(response, self.published.description)
                for status in [Complaint.Status.PENDING, Complaint.Status.REJECTED,
                               Complaint.Status.RESOLVED]:
                    self.assertNotContains(response, self.complaints[status].title)
                    self.assertNotContains(response, self.complaints[status].description[:100])

    def test_detail_content_and_real_company_link_with_optional_logo(self):
        for logo in ["", "companies/logos/public-company.png"]:
            with self.subTest(logo=logo):
                self.company.logo = logo
                self.company.save()
                response = self.client.get(self.detail_url)
                for content in [self.published.title, self.published.description,
                                self.company.name, "Yayında", "Oluşturulma tarihi",
                                "Son güncelleme", "Şirkete Git", "Şikayetlere Dön"]:
                    self.assertContains(response, content)
                company_url = reverse("companies_public:company_detail", args=[self.company.slug])
                self.assertContains(response, f'href="{company_url}"')
                self.assertEqual(self.client.get(company_url).status_code, 200)
                if logo:
                    self.assertContains(response, f'src="{self.company.logo.url}"')

    def test_known_nonpublic_ids_return_404_even_for_owner(self):
        for logged_in in [False, True]:
            if logged_in:
                self.client.force_login(self.owner)
            for status in [Complaint.Status.PENDING, Complaint.Status.REJECTED,
                           Complaint.Status.RESOLVED]:
                complaint = self.complaints[status]
                with self.subTest(logged_in=logged_in, status=status):
                    response = self.client.get(
                        reverse("complaints:public_detail", args=[complaint.pk])
                    )
                    self.assertEqual(response.status_code, 404)
                    self.assertNotContains(response, complaint.title, status_code=404)
                    self.assertNotContains(response, complaint.description, status_code=404)
        self.assertEqual(self.client.get(
            reverse("complaints:public_detail", args=[999999])
        ).status_code, 404)

    def test_inactive_company_is_hidden_across_public_surfaces(self):
        self.company.is_active = False
        self.company.save()
        for url in [self.list_url, self.home_url]:
            response = self.client.get(url)
            self.assertNotContains(response, self.published.title)
        self.assertEqual(self.client.get(self.detail_url).status_code, 404)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(
            reverse("complaints:detail", args=[self.published.pk])
        ), self.published.title)

    def test_public_responses_do_not_expose_owner_profile(self):
        for url in [self.list_url, self.detail_url, self.home_url]:
            with self.subTest(url=url):
                response = self.client.get(url)
                for value in [self.owner.email, self.owner.phone, self.owner.username,
                              self.owner.first_name, self.owner.last_name]:
                    self.assertNotContains(response, value)
                if url == self.detail_url:
                    objects = [response.context["complaint"]]
                elif url == self.list_url:
                    objects = response.context["page_obj"]
                else:
                    objects = response.context["recent_complaints"]
                for complaint in objects:
                    self.assertNotIn("user", complaint._state.fields_cache)

    def test_public_user_content_is_escaped(self):
        self.published.title = '<script>alert(1)</script>'
        self.published.description = '<img src=x onerror="alert(2)">\n<script>alert(3)</script>'
        self.published.save()
        for url in [self.list_url, self.detail_url, self.home_url]:
            with self.subTest(url=url):
                response = self.client.get(url)
                for value in [self.published.title, self.published.description]:
                    self.assertContains(response, escape(value))
                    self.assertNotContains(response, value)

    def test_pagination_is_newest_first_with_stable_ties_and_safe_fallbacks(self):
        from django.utils import timezone

        # Tied timestamps exercise the secondary ordering by primary key.
        extra = [Complaint.objects.create(
            user=self.owner, company=self.company, status=Complaint.Status.PUBLISHED,
            title=f"Paginated complaint {index:02d}", description="Pagination description.",
        ) for index in range(25)]
        Complaint.objects.filter(pk__in=[c.pk for c in extra]).update(created_at=timezone.now())
        expected = list(reversed(extra)) + [self.published]
        seen = []
        for page, count in [(1, 8), (2, 8), (3, 8), (4, 2)]:
            response = self.client.get(self.list_url, {"page": page})
            self.assertEqual(response.status_code, 200)
            objects = list(response.context["page_obj"])
            self.assertEqual(len(objects), count)
            seen.extend(objects)
            if page > 1:
                self.assertContains(response, f'href="?page={page - 1}"')
            if page < 4:
                self.assertContains(response, f'href="?page={page + 1}"')
        self.assertEqual(seen, expected)
        for value, expected_page in [("abc", 1), ("-1", 4), ("999999", 4), ("0", 4)]:
            with self.subTest(page=value):
                response = self.client.get(self.list_url, {"page": value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["page_obj"].number, expected_page)
        home = self.client.get(self.home_url)
        self.assertEqual(list(home.context["recent_complaints"]), expected[:6])
        for complaint in expected[6:]:
            self.assertNotContains(home, complaint.title)

    def test_empty_states_and_empty_pagination(self):
        self.published.status = Complaint.Status.PENDING
        self.published.save()
        for url in [self.list_url, self.home_url]:
            response = self.client.get(url, {"page": "999999"})
            self.assertContains(response, "Henüz yayınlanmış şikayet bulunmuyor.")

    def test_navbar_and_public_access_for_all_roles_without_private_cache_policy(self):
        self.assertEqual(self.list_url, "/sikayetler/")
        self.assertEqual(self.detail_url, f"/sikayetler/{self.published.pk}/")
        self.assertEqual(reverse("complaints:list"), "/sikayetlerim/")
        for role in [None, *User.UserType.values]:
            if role is not None:
                user = User.objects.create_user(
                    username=f"public-viewer-{role}", email=f"viewer-{role}@example.com",
                    user_type=role,
                )
                self.client.force_login(user)
            for url in [self.list_url, self.detail_url, self.home_url]:
                with self.subTest(role=role, url=url):
                    response = self.client.get(url)
                    self.assertContains(response, '<a href="/sikayetler/">Şikayetler</a>', html=True)
                    self.assertNotIn("no-store", response.headers.get("Cache-Control", ""))

    def test_public_views_are_read_only(self):
        for url in [self.list_url, self.detail_url]:
            self.assertEqual(self.client.head(url).status_code, 200)
            for method in ["post", "put", "patch", "delete"]:
                with self.subTest(url=url, method=method):
                    self.assertEqual(getattr(self.client, method)(url).status_code, 405)
        self.published.refresh_from_db()
        self.assertEqual(self.published.status, Complaint.Status.PUBLISHED)


class ComplaintCreateTests(TestCase):
    def create_user(self, username, user_type):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="StrongPass2026!",
            user_type=user_type,
        )

    def create_company(self, name="Complaint Company", is_active=True):
        return Company.objects.create(name=name, is_active=is_active)

    def complaint_data(self, company, **overrides):
        data = {
            "company": company.pk,
            "title": "Teslimat sorunu",
            "description": "Siparişim teslim edilmedi ve şirketten dönüş alamadım.",
        }
        data.update(overrides)
        return data

    def test_anonymous_user_is_redirected_from_create_view(self):
        response = self.client.get(reverse("complaints:create"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_user_can_view_create_form(self):
        user = self.create_user("complaint-user", User.UserType.USER)
        self.create_company()
        self.client.force_login(user)

        response = self.client.get(reverse("complaints:create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Şikayet Oluştur")
        cache_control = response.headers.get("Cache-Control", "")
        self.assertIn("no-store", cache_control)
        self.assertIn("no-cache", cache_control)

    def test_valid_post_creates_pending_complaint_for_logged_in_user(self):
        user = self.create_user("creator", User.UserType.USER)
        company = self.create_company()
        self.client.force_login(user)

        response = self.client.post(
            reverse("complaints:create"),
            self.complaint_data(company),
        )

        self.assertRedirects(response, reverse("dashboard:home"))
        complaint = Complaint.objects.get()
        self.assertEqual(complaint.user, user)
        self.assertEqual(complaint.company, company)
        self.assertEqual(complaint.status, Complaint.Status.PENDING)

    def test_company_and_admin_cannot_use_consumer_create_endpoint(self):
        company = self.create_company()

        for user_type in [User.UserType.COMPANY, User.UserType.ADMIN]:
            with self.subTest(user_type=user_type):
                user = self.create_user(f"blocked-{user_type.lower()}", user_type)
                self.client.force_login(user)

                get_response = self.client.get(reverse("complaints:create"))
                post_response = self.client.post(
                    reverse("complaints:create"),
                    self.complaint_data(company),
                )

                self.assertEqual(get_response.status_code, 403)
                self.assertEqual(post_response.status_code, 403)
                self.assertFalse(Complaint.objects.filter(user=user).exists())
                self.client.logout()

    def test_status_and_user_post_manipulation_is_ignored(self):
        user = self.create_user("real-owner", User.UserType.USER)
        other = self.create_user("other-owner", User.UserType.USER)
        company = self.create_company()
        self.client.force_login(user)

        response = self.client.post(
            reverse("complaints:create"),
            self.complaint_data(
                company,
                user=other.pk,
                user_id=other.pk,
                owner_id=other.pk,
                status=Complaint.Status.PUBLISHED,
            ),
        )

        self.assertRedirects(response, reverse("dashboard:home"))
        complaint = Complaint.objects.get()
        self.assertEqual(complaint.user, user)
        self.assertEqual(complaint.status, Complaint.Status.PENDING)

    def test_inactive_company_is_rejected(self):
        user = self.create_user("inactive-company-user", User.UserType.USER)
        inactive_company = self.create_company("Inactive Company", is_active=False)
        self.client.force_login(user)

        response = self.client.post(
            reverse("complaints:create"),
            self.complaint_data(inactive_company),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("company", response.context["form"].errors)
        self.assertFalse(Complaint.objects.exists())

    def test_short_or_whitespace_content_is_rejected(self):
        user = self.create_user("validation-user", User.UserType.USER)
        company = self.create_company()
        self.client.force_login(user)

        response = self.client.post(
            reverse("complaints:create"),
            self.complaint_data(company, title="   abc   ", description="   kısa   "),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("title", response.context["form"].errors)
        self.assertIn("description", response.context["form"].errors)
        self.assertFalse(Complaint.objects.exists())

    def test_complaint_title_is_escaped_in_panel(self):
        user = self.create_user("xss-user", User.UserType.USER)
        company = self.create_company()
        self.client.force_login(user)

        response = self.client.post(
            reverse("complaints:create"),
            self.complaint_data(
                company,
                title="<script>alert(1)</script> sorunu",
                description="Bu açıklama yeterince uzun ve script çalıştırmamalı.",
            ),
        )
        self.assertRedirects(response, reverse("dashboard:home"))

        panel_response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(panel_response.status_code, 200)
        self.assertNotContains(panel_response, "<script>alert(1)</script>")
        self.assertContains(panel_response, "&lt;script&gt;alert(1)&lt;/script&gt; sorunu")

    def test_create_requires_csrf_when_csrf_checks_are_enforced(self):
        user = self.create_user("csrf-complaint-user", User.UserType.USER)
        company = self.create_company()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)

        response = csrf_client.post(
            reverse("complaints:create"),
            self.complaint_data(company),
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Complaint.objects.exists())

    def test_panel_shows_only_logged_in_users_recent_complaints(self):
        user_a = self.create_user("owner-a", User.UserType.USER)
        user_b = self.create_user("owner-b", User.UserType.USER)
        company = self.create_company()
        Complaint.objects.create(
            user=user_a,
            company=company,
            title="User A complaint",
            description="User A için yeterince uzun açıklama.",
        )
        Complaint.objects.create(
            user=user_b,
            company=company,
            title="User B complaint",
            description="User B için yeterince uzun açıklama.",
        )
        self.client.force_login(user_b)

        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "User B complaint")
        self.assertNotContains(response, "User A complaint")
