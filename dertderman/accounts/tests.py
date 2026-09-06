from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from companies.models import Company, CompanyMembership


User = get_user_model()


class AuthenticationSecurityTests(TestCase):
    def register_data(self, **overrides):
        data = {
            "username": "new-user",
            "email": "new-user@example.com",
            "first_name": "New",
            "last_name": "User",
            "phone": "5551234567",
            "password1": "StrongPass2026!",
            "password2": "StrongPass2026!",
        }
        data.update(overrides)
        return data

    def create_user(self, username, user_type):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="StrongPass2026!",
            user_type=user_type,
        )

    def test_public_register_creates_user_and_hashes_password(self):
        raw_password = "StrongPass2026!"

        response = self.client.post(
            reverse("accounts:register"),
            self.register_data(password1=raw_password, password2=raw_password),
        )

        self.assertRedirects(response, reverse("dashboard:home"))
        user = User.objects.get(username="new-user")
        self.assertEqual(user.user_type, User.UserType.USER)
        self.assertNotEqual(user.password, raw_password)
        self.assertTrue(user.check_password(raw_password))
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_public_register_prevents_privilege_escalation(self):
        response = self.client.post(
            reverse("accounts:register"),
            self.register_data(
                username="attacker",
                email="attacker@example.com",
                user_type=User.UserType.ADMIN,
                is_staff="True",
                is_superuser="True",
                is_verified="True",
                groups=["1"],
                user_permissions=["1"],
            ),
        )

        self.assertRedirects(response, reverse("dashboard:home"))
        user = User.objects.get(username="attacker")
        self.assertEqual(user.user_type, User.UserType.USER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_verified)
        self.assertEqual(user.groups.count(), 0)
        self.assertEqual(user.user_permissions.count(), 0)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_anonymous_users_are_redirected_from_protected_views(self):
        protected_urls = [
            reverse("dashboard:home"),
            reverse("accounts:profile"),
            reverse("accounts:profile_edit"),
            reverse("accounts:password_change"),
            reverse("companies:company_panel"),
            reverse("adminx:home"),
        ]

        for url in protected_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                login_route = "adminx:login" if url.startswith("/yonetim/") else "accounts:login"
                self.assertIn(reverse(login_route), response["Location"])

    def test_authenticated_user_cannot_view_login_or_register_forms(self):
        user = self.create_user("already-auth", User.UserType.USER)
        self.client.force_login(user)

        for url in [reverse("accounts:login"), reverse("accounts:register")]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(response, reverse("dashboard:home"))

    def test_user_authorization(self):
        user = self.create_user("regular", User.UserType.USER)
        self.client.force_login(user)

        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("companies:company_panel")).status_code,
            403,
        )
        self.assertEqual(self.client.get(reverse("adminx:home")).status_code, 403)

    def test_company_authorization(self):
        company = self.create_user("company", User.UserType.COMPANY)
        self.client.force_login(company)

        self.assertEqual(
            self.client.get(reverse("companies:company_panel")).status_code,
            403,
        )
        self.assertEqual(self.client.get(reverse("adminx:home")).status_code, 403)
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 403)

    def test_admin_authorization(self):
        admin = self.create_user("custom-admin", User.UserType.ADMIN)
        self.client.force_login(admin)

        self.assertEqual(self.client.get(reverse("adminx:home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("companies:company_panel")).status_code,
            403,
        )

    def test_login_redirects_by_role_and_ignores_external_next(self):
        role_expectations = [
            (User.UserType.USER, reverse("dashboard:home")),
            (User.UserType.COMPANY, reverse("companies:company_panel")),
            (User.UserType.ADMIN, reverse("adminx:home")),
        ]

        for index, (user_type, expected_url) in enumerate(role_expectations):
            username = f"login-{index}"
            self.create_user(username, user_type)
            response = self.client.post(
                f"{reverse('accounts:login')}?next=https://evil.example",
                {
                    "username": username,
                    "password": "StrongPass2026!",
                },
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Location"], expected_url)
            self.client.logout()

    def test_valid_login_authenticates_user_and_redirects_to_panel(self):
        user = self.create_user("valid-login", User.UserType.USER)

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "valid-login",
                "password": "StrongPass2026!",
            },
        )

        self.assertRedirects(response, reverse("dashboard:home"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_wrong_password_does_not_authenticate(self):
        self.create_user("wrong-login", User.UserType.USER)

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "wrong-login",
                "password": "WrongPass2026!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_with_unknown_role_fails_closed_to_home(self):
        user = self.create_user("unknown-role", User.UserType.USER)
        User.objects.filter(pk=user.pk).update(user_type="UNKNOWN")

        response = self.client.post(
            f"{reverse('accounts:login')}?next=https://evil.example",
            {
                "username": "unknown-role",
                "password": "StrongPass2026!",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("core:home"))

    def test_logout_post_closes_session_get_does_not(self):
        user = self.create_user("logout-user", User.UserType.USER)
        self.client.force_login(user)

        get_response = self.client.get(reverse("accounts:logout"))

        self.assertEqual(get_response.status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

        post_response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(post_response, reverse("core:home"))
        self.assertNotIn("_auth_user_id", self.client.session)

        protected_response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(protected_response.status_code, 302)
        self.assertIn(reverse("accounts:login"), protected_response["Location"])

    def test_logout_requires_csrf_when_csrf_checks_are_enforced(self):
        user = self.create_user("csrf-logout-user", User.UserType.USER)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)

        response = csrf_client.post(reverse("accounts:logout"))

        self.assertEqual(response.status_code, 403)
        self.assertIn("_auth_user_id", csrf_client.session)

    def test_register_and_login_require_csrf_when_csrf_checks_are_enforced(self):
        csrf_client = Client(enforce_csrf_checks=True)
        register_response = csrf_client.post(
            reverse("accounts:register"),
            self.register_data(username="csrf-register", email="csrf-register@example.com"),
        )

        self.assertEqual(register_response.status_code, 403)
        self.assertFalse(User.objects.filter(username="csrf-register").exists())

        self.create_user("csrf-login", User.UserType.USER)
        login_response = csrf_client.post(
            reverse("accounts:login"),
            {
                "username": "csrf-login",
                "password": "StrongPass2026!",
            },
        )

        self.assertEqual(login_response.status_code, 403)
        self.assertNotIn("_auth_user_id", csrf_client.session)

    def test_register_logout_login_smoke_chain(self):
        raw_password = "StrongPass2026!"

        register_response = self.client.post(
            reverse("accounts:register"),
            self.register_data(
                username="smoke-user",
                email="smoke-user@example.com",
                password1=raw_password,
                password2=raw_password,
            ),
        )
        user = User.objects.get(username="smoke-user")

        self.assertRedirects(register_response, reverse("dashboard:home"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

        logout_response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(logout_response, reverse("core:home"))
        self.assertNotIn("_auth_user_id", self.client.session)

        protected_response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(protected_response.status_code, 302)
        self.assertIn(reverse("accounts:login"), protected_response["Location"])

        login_response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "smoke-user",
                "password": raw_password,
            },
        )

        self.assertRedirects(login_response, reverse("dashboard:home"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_profile_requires_login_and_authenticated_user_can_view_profile(self):
        anonymous_response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(anonymous_response.status_code, 302)
        self.assertIn(reverse("accounts:login"), anonymous_response["Location"])

        user = self.create_user("profile-user", User.UserType.USER)
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "profile-user")
        self.assertNotContains(response, "StrongPass2026!")

    def test_profile_edit_updates_allowed_fields(self):
        user = self.create_user("editable", User.UserType.USER)
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "first_name": "Updated",
                "last_name": "Person",
                "email": "updated@example.com",
                "phone": "5559876543",
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Updated")
        self.assertEqual(user.last_name, "Person")
        self.assertEqual(user.email, "updated@example.com")
        self.assertEqual(user.phone, "5559876543")

    def test_profile_edit_prevents_privilege_escalation(self):
        user = self.create_user("profile-attacker", User.UserType.USER)
        original_date_joined = user.date_joined
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "username": "changed",
                "first_name": "Allowed",
                "last_name": "Change",
                "email": "profile-attacker-new@example.com",
                "phone": "5551112233",
                "user_type": User.UserType.ADMIN,
                "is_staff": "True",
                "is_superuser": "True",
                "is_verified": "True",
                "groups": ["1"],
                "user_permissions": ["1"],
                "date_joined": "2000-01-01T00:00:00Z",
            },
        )

        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.username, "profile-attacker")
        self.assertEqual(user.user_type, User.UserType.USER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_verified)
        self.assertEqual(user.groups.count(), 0)
        self.assertEqual(user.user_permissions.count(), 0)
        self.assertEqual(user.date_joined, original_date_joined)

    def test_profile_edit_does_not_modify_another_user(self):
        user_a = self.create_user("user-a", User.UserType.USER)
        user_b = self.create_user("user-b", User.UserType.USER)
        self.client.force_login(user_a)

        response = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "id": user_b.pk,
                "user_id": user_b.pk,
                "first_name": "Changed A",
                "last_name": "Only A",
                "email": "user-a-new@example.com",
                "phone": "5554443322",
            },
        )

        self.assertEqual(response.status_code, 302)
        user_a.refresh_from_db()
        user_b.refresh_from_db()
        self.assertEqual(user_a.email, "user-a-new@example.com")
        self.assertEqual(user_b.email, "user-b@example.com")
        self.assertEqual(user_b.first_name, "")
        self.assertEqual(user_b.phone, "")

    def test_profile_edit_duplicate_email_returns_form_error(self):
        user = self.create_user("duplicate-editor", User.UserType.USER)
        other = self.create_user("duplicate-owner", User.UserType.USER)
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:profile_edit"),
            {
                "first_name": "Duplicate",
                "last_name": "Email",
                "email": other.email,
                "phone": "5553332211",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        user.refresh_from_db()
        self.assertEqual(user.email, "duplicate-editor@example.com")

    def test_password_change_updates_password_and_keeps_session(self):
        user = self.create_user("password-user", User.UserType.USER)
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": "StrongPass2026!",
                "new_password1": "NewStrongPass2027!",
                "new_password2": "NewStrongPass2027!",
            },
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertFalse(user.check_password("StrongPass2026!"))
        self.assertTrue(user.check_password("NewStrongPass2027!"))
        self.assertEqual(self.client.get(reverse("accounts:profile")).status_code, 200)

    def test_password_change_rejects_wrong_old_password(self):
        user = self.create_user("wrong-old-password", User.UserType.USER)
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "old_password": "WrongPass2026!",
                "new_password1": "NewStrongPass2027!",
                "new_password2": "NewStrongPass2027!",
            },
        )

        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password("StrongPass2026!"))
        self.assertFalse(user.check_password("NewStrongPass2027!"))

    def test_profile_edit_and_password_change_require_csrf(self):
        user = self.create_user("csrf-profile-user", User.UserType.USER)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)

        profile_response = csrf_client.post(
            reverse("accounts:profile_edit"),
            {
                "first_name": "Blocked",
                "last_name": "By CSRF",
                "email": "csrf-profile-new@example.com",
                "phone": "5552223344",
            },
        )
        password_response = csrf_client.post(
            reverse("accounts:password_change"),
            {
                "old_password": "StrongPass2026!",
                "new_password1": "NewStrongPass2027!",
                "new_password2": "NewStrongPass2027!",
            },
        )

        self.assertEqual(profile_response.status_code, 403)
        self.assertEqual(password_response.status_code, 403)
        user.refresh_from_db()
        self.assertEqual(user.email, "csrf-profile-user@example.com")
        self.assertTrue(user.check_password("StrongPass2026!"))

    def test_sensitive_user_pages_have_no_store_cache_headers(self):
        user = self.create_user("cache-user", User.UserType.USER)
        self.client.force_login(user)
        urls = [
            reverse("dashboard:home"),
            reverse("accounts:profile"),
            reverse("accounts:profile_edit"),
            reverse("accounts:password_change"),
            reverse("accounts:login"),
            reverse("accounts:register"),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                cache_control = response.headers.get("Cache-Control", "")
                self.assertIn("no-store", cache_control)
                self.assertIn("no-cache", cache_control)

    def test_role_protected_company_and_admin_pages_have_no_store_cache_headers(self):
        company_user = self.create_user("cache-company-user", User.UserType.COMPANY)
        company = Company.objects.create(name="Cache Company", is_active=True)
        CompanyMembership.objects.create(
            user=company_user,
            company=company,
            role=CompanyMembership.Role.OWNER,
        )
        self.client.force_login(company_user)

        company_response = self.client.get(reverse("companies:company_panel"))
        self.assertEqual(company_response.status_code, 200)
        company_cache_control = company_response.headers.get("Cache-Control", "")
        self.assertIn("no-store", company_cache_control)
        self.assertIn("no-cache", company_cache_control)

        self.client.logout()
        admin = self.create_user("cache-admin-user", User.UserType.ADMIN)
        self.client.force_login(admin)

        admin_response = self.client.get(reverse("adminx:home"))
        self.assertEqual(admin_response.status_code, 200)
        admin_cache_control = admin_response.headers.get("Cache-Control", "")
        self.assertIn("no-store", admin_cache_control)
        self.assertIn("no-cache", admin_cache_control)
