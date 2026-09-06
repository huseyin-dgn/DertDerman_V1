from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from .auth_views import LOGIN_ERROR


class AdminLoginTests(TestCase):
    password = "AdminEntryPassword2026!"

    @classmethod
    def setUpTestData(cls):
        cls.users = {
            role: get_user_model().objects.create_user(username=f"entry-{role}", email=f"entry-{role}@example.com", user_type=role, password=cls.password)
            for role in ["ADMIN", "USER", "COMPANY", "UNKNOWN"]
        }

    def test_anonymous_entry_and_login_are_no_store(self):
        response = self.client.get("/yonetim/")
        self.assertRedirects(response, "/yonetim/giris/?next=/yonetim/")
        self.assertIn("no-store", response["Cache-Control"])
        response = self.client.get("/yonetim/giris/")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "adminx/login.html")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotContains(response, "/hesap/kayit/")
        self.assertNotContains(response, "data-motion-region")

    def test_admin_login_rotates_session_and_ignores_all_next_values(self):
        admin = self.users["ADMIN"]
        self.assertFalse(admin.is_staff)
        self.assertFalse(admin.is_superuser)
        for next_url in ["https://example.com/steal", "//example.com/", "/panel/", "/yonetim/giris/", "/yonetim/blog/"]:
            with self.subTest(next=next_url):
                client = Client(enforce_csrf_checks=True)
                session = client.session
                session["pre_login"] = "session rotation"
                session.save()
                old_key = session.session_key
                client.get("/yonetim/giris/")
                response = client.post("/yonetim/giris/?next=https://example.com/", {
                    "username": admin.username, "password": self.password, "next": next_url,
                    "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
                })
                self.assertRedirects(response, "/yonetim/")
                self.assertIn("no-store", response["Cache-Control"])
                self.assertEqual(int(client.session["_auth_user_id"]), admin.pk)
                self.assertNotEqual(client.session.session_key, old_key)

    def test_non_admin_credentials_and_staff_flags_never_create_session(self):
        for role in ["USER", "COMPANY", "UNKNOWN"]:
            user = self.users[role]
            user.is_staff = user.is_superuser = True
            user.save()
            client = Client()
            response = client.post("/yonetim/giris/", {"username": user.username, "password": self.password})
            self.assertContains(response, LOGIN_ERROR, count=1)
            self.assertIn("no-store", response["Cache-Control"])
            self.assertNotIn("_auth_user_id", client.session)
            self.assertRedirects(client.get("/yonetim/"), "/yonetim/giris/?next=/yonetim/")

    def test_wrong_unknown_and_inactive_credentials_share_generic_error(self):
        for username in [self.users["ADMIN"].username, "missing-account"]:
            response = self.client.post("/yonetim/giris/", {"username": username, "password": "wrong-password"})
            self.assertContains(response, LOGIN_ERROR, count=1)
            self.assertNotIn("_auth_user_id", self.client.session)
            self.assertNotContains(response, "wrong-password")
        admin = self.users["ADMIN"]
        admin.is_active = False
        admin.save()
        response = self.client.post("/yonetim/giris/", {"username": admin.username, "password": self.password})
        self.assertContains(response, LOGIN_ERROR, count=1)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_csrf_required_and_logout_keeps_post_csrf_contract(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post("/yonetim/giris/", {"username": self.users["ADMIN"].username, "password": self.password}).status_code, 403)
        self.assertNotIn("_auth_user_id", client.session)
        client.force_login(self.users["ADMIN"])
        old_key = client.cookies["sessionid"].value
        self.assertEqual(client.get("/hesap/cikis/").status_code, 405)
        self.assertEqual(client.post("/hesap/cikis/").status_code, 403)
        client.get("/yonetim/")
        self.assertRedirects(client.post("/hesap/cikis/", {"csrfmiddlewaretoken": client.cookies["csrftoken"].value}), "/")
        client.cookies["sessionid"] = old_key
        self.assertRedirects(client.get("/yonetim/"), "/yonetim/giris/?next=/yonetim/")

    def test_existing_sessions_keep_role_boundary_and_django_admin_stays_404(self):
        for role, user in self.users.items():
            self.client.force_login(user)
            response = self.client.get("/yonetim/giris/")
            if role == "ADMIN":
                self.assertRedirects(response, "/yonetim/")
            else:
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.client.get("/yonetim/").status_code, 403)
                self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
            response = self.client.get("/django-admin/")
            self.assertEqual(response.status_code, 404)
            self.assertTemplateUsed(response, "404.html")
