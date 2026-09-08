from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from companies.models import Company, CompanyMembership
from complaints.models import Complaint


User = get_user_model()


class RouteAccessTests(TestCase):
    password = "RouteAccess2026!"

    @classmethod
    def setUpTestData(cls):
        cls.users = {
            role: User.objects.create_user(
                username=f"route-{role}", email=f"route-{role}@example.com",
                password=cls.password, user_type=role,
            ) for role in [*User.UserType.values, "UNKNOWN"]
        }
        cls.company = Company.objects.create(name="Owned route company", is_verified=True)
        cls.foreign_company = Company.objects.create(name="Secret foreign company")
        cls.membership = CompanyMembership.objects.create(
            user=cls.users["COMPANY"], company=cls.company,
        )
        cls.pending = Complaint.objects.create(
            user=cls.users["USER"], company=cls.company,
            title="Private route complaint", description="Sensitive pending complaint description.",
        )
        cls.published = Complaint.objects.create(
            user=cls.users["USER"], company=cls.company, status=Complaint.Status.PUBLISHED,
            title="Public route complaint", description="Published complaint for public route checks.",
        )

    def setUp(self):
        self.routes = {
            "USER": [
                "/panel/", "/hesap/profil/", "/hesap/profil/duzenle/",
                "/hesap/sifre-degistir/", "/sikayet-olustur/", "/sikayetlerim/",
                f"/sikayetlerim/{self.pending.pk}/",
            ],
            "COMPANY": ["/sirket-panel/", f"/sirket-panel/{self.company.slug}/"],
            "ADMIN": ["/yonetim/", "/yonetim/sikayetler/", f"/yonetim/sikayetler/{self.pending.pk}/"],
        }
        self.public_routes = [
            "/", "/sirketler/", f"/sirketler/{self.company.slug}/",
            "/sikayetler/", f"/sikayetler/{self.published.pk}/",
        ]
        self.destinations = {"USER": "/panel/", "COMPANY": "/sirket-panel/", "ADMIN": "/yonetim/", "UNKNOWN": "/"}

    def assert_private_cache(self, response):
        directives = {value.strip() for value in response["Cache-Control"].split(",")}
        self.assertTrue({"no-store", "no-cache", "private", "must-revalidate", "max-age=0"} <= directives)
        self.assertIn("Expires", response.headers)

    def test_direct_url_access_matrix_including_unknown_role(self):
        for role in [None, *self.users]:
            client = Client()
            if role:
                client.force_login(self.users[role])
            for required_role, urls in self.routes.items():
                for url in urls:
                    with self.subTest(role=role, url=url):
                        response = client.get(url)
                        if role is None:
                            self.assertRedirects(response, f"{'/yonetim/giris/' if url.startswith('/yonetim/') else '/hesap/giris/'}?next={url}")
                            self.assert_private_cache(response)
                        elif role == required_role:
                            self.assertEqual(response.status_code, 200)
                            self.assert_private_cache(response)
                        else:
                            self.assertEqual(response.status_code, 403)
                        if role != required_role:
                            self.assertNotIn(self.pending.description, response.content.decode())
            for url in self.public_routes:
                with self.subTest(role=role, public_url=url):
                    response = client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn("no-store", response.headers.get("Cache-Control", ""))
            for url in ["/hesap/giris/", "/hesap/kayit/"]:
                response = client.get(url)
                if role is None:
                    self.assertEqual(response.status_code, 200)
                else:
                    self.assertRedirects(response, self.destinations[role])
                    self.assertNotContains(response, 'name="password"', status_code=302)
                self.assert_private_cache(response)
            self.assertRedirects(client.get("/hesap/"), self.destinations[role] if role else "/hesap/giris/")

    def test_django_admin_and_default_aliases_are_disabled_for_every_role(self):
        for role in [None, *self.users]:
            client = Client()
            if role:
                client.force_login(self.users[role])
            for url in ["/django-admin/", "/django-admin/login/", "/django-admin/accounts/user/", "/admin/", "/admin/login/"]:
                with self.subTest(role=role, url=url):
                    self.assertEqual(client.get(url).status_code, 404)
        admin = self.users["ADMIN"]
        admin.is_staff = admin.is_superuser = True
        admin.save()
        self.client.force_login(admin)
        self.assertEqual(self.client.get("/django-admin/").status_code, 404)

    def test_profile_and_password_posts_are_user_only(self):
        for role in ["COMPANY", "ADMIN", "UNKNOWN"]:
            user = self.users[role]
            self.client.force_login(user)
            for url, data in [
                ("/hesap/profil/duzenle/", {"email": "changed@example.com", "first_name": "Changed"}),
                ("/hesap/sifre-degistir/", {"old_password": self.password,
                    "new_password1": "ChangedPassword2027!", "new_password2": "ChangedPassword2027!"}),
                ("/sikayet-olustur/", {"company": self.company.pk, "title": "Forbidden complaint",
                    "description": "This complaint must never be created."}),
            ]:
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.client.post(url, data).status_code, 403)
            user.refresh_from_db()
            self.assertEqual(user.email, f"route-{role}@example.com")
            self.assertTrue(user.check_password(self.password))
        self.assertEqual(Complaint.objects.count(), 2)

    def test_moderation_actions_authorize_before_mutation(self):
        for role in [None, *self.users]:
            client = Client()
            if role:
                client.force_login(self.users[role])
            for action in ["yayinla", "reddet"]:
                url = f"/yonetim/sikayetler/{self.pending.pk}/{action}/"
                with self.subTest(role=role, action=action):
                    self.assertEqual(client.get(url).status_code, 302 if role is None else 405 if role == "ADMIN" else 403)
                    if role != "ADMIN":
                        response = client.post(url)
                        if role is None:
                            self.assertRedirects(response, f"{'/yonetim/giris/' if url.startswith('/yonetim/') else '/hesap/giris/'}?next={url}")
                        else:
                            self.assertEqual(response.status_code, 403)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Complaint.Status.PENDING)

    def test_login_ignores_external_and_wrong_role_next_and_rotates_session(self):
        for role, user in self.users.items():
            for next_url in ["/yonetim/", "/panel/", "https://example.com/", "//example.com/"]:
                with self.subTest(role=role, next_url=next_url):
                    client = Client()
                    session = client.session
                    session["pre_login"] = "session rotation check"
                    session.save()
                    old_key = session.session_key
                    response = client.post("/hesap/giris/?next=/yonetim/", {
                        "username": user.username, "password": self.password, "next": next_url,
                    })
                    self.assertRedirects(response, self.destinations[role])
                    self.assertNotEqual(client.session.session_key, old_key)

    def test_logout_ignores_next_and_invalidates_replayed_session_for_all_private_urls(self):
        for role in ["USER", "COMPANY", "ADMIN"]:
            client = Client()
            client.force_login(self.users[role])
            old_session = client.cookies[settings.SESSION_COOKIE_NAME].value
            self.assertEqual(client.get("/hesap/cikis/").status_code, 405)
            self.assertIn("_auth_user_id", client.session)
            self.assertRedirects(client.post("/hesap/cikis/?next=/yonetim/", {"next": "/panel/"}), "/")
            self.assertNotIn("_auth_user_id", client.session)
            for replay in [False, True]:
                if replay:
                    client.cookies[settings.SESSION_COOKIE_NAME] = old_session
                for urls in self.routes.values():
                    for url in urls:
                        with self.subTest(role=role, replay=replay, url=url):
                            response = client.get(url)
                            self.assertRedirects(response, f"{'/yonetim/giris/' if url.startswith('/yonetim/') else '/hesap/giris/'}?next={url}")
                            self.assert_private_cache(response)

    def test_object_authorization_and_publication_are_preserved(self):
        other = User.objects.create_user(username="other-route-user", email="other-route@example.com")
        self.client.force_login(other)
        response = self.client.get(f"/sikayetlerim/{self.pending.pk}/")
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, self.pending.description, status_code=404)
        self.client.force_login(self.users["COMPANY"])
        response = self.client.get(f"/sirket-panel/{self.foreign_company.slug}/")
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, self.foreign_company.name, status_code=403)
        for field in ["membership", "company"]:
            target = self.membership if field == "membership" else self.company
            target.is_active = False
            target.save()
            for url in self.routes["COMPANY"]:
                self.assertEqual(self.client.get(url).status_code, 403)
            target.is_active = True
            target.save()
        for status in [Complaint.Status.PENDING, Complaint.Status.REJECTED, Complaint.Status.RESOLVED]:
            self.pending.status = status
            self.pending.save()
            response = Client().get(f"/sikayetler/{self.pending.pk}/")
            self.assertEqual(response.status_code, 404)
            self.assertNotContains(response, self.pending.description, status_code=404)
        self.company.is_active = False
        self.company.save()
        self.assertEqual(Client().get(f"/sikayetler/{self.published.pk}/").status_code, 404)

    def test_register_login_logout_smoke_and_role_logins(self):
        client = Client()
        self.assertRedirects(client.post("/hesap/kayit/", {
            "username": "route-smoke-user", "email": "route-smoke@example.com",
            "password1": self.password, "password2": self.password,
        }), "/panel/")
        self.assertEqual(client.get("/panel/").status_code, 200)
        self.assertRedirects(client.post("/hesap/cikis/"), "/")
        self.assertRedirects(client.get("/panel/"), "/hesap/giris/?next=/panel/")
        self.assertRedirects(client.post("/hesap/giris/", {
            "username": "route-smoke-user", "password": self.password,
        }), "/panel/")
        self.assertEqual(client.get("/sikayetlerim/").status_code, 200)
        self.assertRedirects(client.post("/hesap/cikis/"), "/")
        self.assertRedirects(client.get("/sikayetlerim/"), "/hesap/giris/?next=/sikayetlerim/")
        for role in ["COMPANY", "ADMIN"]:
            client = Client()
            self.assertRedirects(client.post("/hesap/giris/", {
                "username": self.users[role].username, "password": self.password,
            }), self.destinations[role])
            if role == "COMPANY":
                self.assertEqual(client.get(f"/sirket-panel/{self.company.slug}/").status_code, 200)
                self.assertEqual(client.get(f"/sirket-panel/{self.foreign_company.slug}/").status_code, 403)

    def test_session_cookie_flags_and_csrf_on_all_state_changing_routes(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, "Lax")
        csrf_client = Client(enforce_csrf_checks=True)
        for url in ["/hesap/giris/", "/hesap/kayit/"]:
            self.assertEqual(csrf_client.post(url).status_code, 403)
        csrf_client.force_login(self.users["USER"])
        for url in ["/hesap/cikis/", "/hesap/profil/duzenle/", "/hesap/sifre-degistir/", "/sikayet-olustur/"]:
            self.assertEqual(csrf_client.post(url).status_code, 403)
        csrf_client.force_login(self.users["ADMIN"])
        for action in ["yayinla", "reddet"]:
            self.assertEqual(csrf_client.post(f"/yonetim/sikayetler/{self.pending.pk}/{action}/").status_code, 403)

    def test_navbar_only_offers_consumer_profile_to_user(self):
        for role, user in self.users.items():
            self.client.force_login(user)
            response = self.client.get("/")
            if role == "USER":
                self.assertContains(response, 'href="/hesap/profil/"')
            else:
                self.assertNotContains(response, 'href="/hesap/profil/"')
