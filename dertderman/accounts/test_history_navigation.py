from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from companies.models import Company, CompanyMembership


User = get_user_model()
PASSWORD = "HistoryPolicy2026!"


class IntendedLoginRedirectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="history-user", email="history-user@example.com",
            password=PASSWORD, user_type=User.UserType.USER,
        )
        cls.company_user = User.objects.create_user(
            username="history-company", email="history-company@example.com",
            password=PASSWORD, user_type=User.UserType.COMPANY,
        )
        cls.admin = User.objects.create_user(
            username="history-admin", email="history-admin@example.com",
            password=PASSWORD, user_type=User.UserType.ADMIN,
        )
        cls.company = Company.objects.create(
            name="History Redirect Company", is_active=True, is_verified=True,
        )
        CompanyMembership.objects.create(
            user=cls.company_user, company=cls.company,
            role=CompanyMembership.Role.OWNER,
        )

    def test_company_detail_login_returns_to_create_with_company_preselected(self):
        target = f'{reverse("complaints:create")}?company={self.company.pk}'
        detail = self.client.get(reverse("companies_public:company_detail", args=[self.company.slug]))
        self.assertContains(detail, f'href="{target}"')

        protected = self.client.get(target)
        login_url = protected["Location"]
        self.assertEqual(parse_qs(urlsplit(login_url).query)["next"], [target])

        response = self.client.post(login_url, {
            "username": self.user.username,
            "password": PASSWORD,
        })
        self.assertRedirects(response, target, fetch_redirect_response=False)
        create_page = self.client.get(response["Location"])
        self.assertEqual(create_page.context["form"]["company"].value(), self.company.pk)

    def test_external_and_wrong_role_next_values_use_role_defaults(self):
        cases = (
            (reverse("accounts:login"), {"username": self.user.username}, "/panel/", "/yonetim/"),
            (reverse("company_auth:login"), {"email": self.company_user.email}, "/sirket-panel/", "/panel/"),
            (reverse("adminx:login"), {"username": self.admin.username}, "/yonetim/", "/panel/"),
        )
        for route, identity, fallback, wrong_role in cases:
            for unsafe in ("https://evil.example/", "https://another-domain.example/path", wrong_role):
                with self.subTest(route=route, next=unsafe):
                    client = Client()
                    response = client.post(route, {**identity, "password": PASSWORD, "next": unsafe})
                    self.assertRedirects(response, fallback, fetch_redirect_response=False)

    def test_company_and_admin_safe_private_next_values_are_preserved(self):
        cases = (
            (reverse("company_auth:login"), {"email": self.company_user.email}, "/sirket-panel/profil/?tab=media"),
            (reverse("adminx:login"), {"username": self.admin.username}, "/yonetim/blog/?page=2"),
        )
        for route, identity, target in cases:
            with self.subTest(route=route):
                client = Client()
                response = client.post(route, {**identity, "password": PASSWORD, "next": target})
                self.assertRedirects(response, target, fetch_redirect_response=False)


class HistorySessionPolicyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {
            role: User.objects.create_user(
                username=f"history-{role.lower()}", email=f"history-{role.lower()}@example.com",
                password=PASSWORD, user_type=role,
            )
            for role in User.UserType.values
        }
        company = Company.objects.create(name="History Session Company", is_active=True, is_verified=True)
        CompanyMembership.objects.create(
            user=cls.users[User.UserType.COMPANY], company=company,
            role=CompanyMembership.Role.OWNER,
        )

    def assert_private_cache(self, response):
        directives = {item.strip() for item in response["Cache-Control"].split(",")}
        self.assertTrue({"no-store", "no-cache", "private", "must-revalidate", "max-age=0"} <= directives)
        self.assertIn("Expires", response.headers)

    def test_endpoint_is_post_only_and_csrf_protected(self):
        route = reverse("accounts:history_invalidate")
        self.assertEqual(Client().post(route).status_code, 401)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.users[User.UserType.USER])
        self.assertEqual(client.get(route).status_code, 405)
        self.assertIn("_auth_user_id", client.session)
        self.assertEqual(client.post(route).status_code, 403)
        self.assertIn("_auth_user_id", client.session)

    def test_post_flushes_each_role_session_and_private_route_requires_login(self):
        cases = (
            (User.UserType.USER, "/panel/", "/hesap/giris/?next=/panel/"),
            (User.UserType.COMPANY, "/sirket-panel/", "/hesap/giris/?next=/sirket-panel/"),
            (User.UserType.ADMIN, "/yonetim/", "/yonetim/giris/?next=/yonetim/"),
        )
        for role, private_url, login_url in cases:
            with self.subTest(role=role):
                client = Client()
                client.force_login(self.users[role])
                old_session = client.cookies[settings.SESSION_COOKIE_NAME].value
                before = client.get(private_url)
                self.assertEqual(before.status_code, 200)
                self.assert_private_cache(before)
                response = client.post(reverse("accounts:history_invalidate"))
                self.assertEqual(response.status_code, 204)
                self.assertNotIn("_auth_user_id", client.session)
                after = client.get(private_url)
                self.assertRedirects(after, login_url, fetch_redirect_response=False)
                self.assert_private_cache(after)
                client.cookies[settings.SESSION_COOKIE_NAME] = old_session
                replay = client.get(private_url)
                self.assertRedirects(replay, login_url, fetch_redirect_response=False)

    def test_refresh_equivalent_and_normal_get_navigation_keep_session(self):
        for role, private_url in (
            (User.UserType.USER, "/panel/"),
            (User.UserType.COMPANY, "/sirket-panel/"),
            (User.UserType.ADMIN, "/yonetim/"),
        ):
            with self.subTest(role=role):
                client = Client()
                client.force_login(self.users[role])
                self.assertEqual(client.get(private_url).status_code, 200)
                self.assertEqual(client.get(private_url).status_code, 200)
                self.assertEqual(client.get(reverse("core:home")).status_code, 200)
                self.assertEqual(int(client.session["_auth_user_id"]), self.users[role].pk)

    def test_history_detection_uses_only_browser_traversal_signals(self):
        script = (Path(settings.BASE_DIR) / "static/js/history-session.js").read_text(encoding="utf-8")
        self.assertIn("navigation?.type === 'back_forward'", script)
        self.assertIn("event.persisted", script)
        self.assertIn("method: 'POST'", script)
        self.assertNotIn("beforeunload", script)
        self.assertNotIn("popstate", script)
