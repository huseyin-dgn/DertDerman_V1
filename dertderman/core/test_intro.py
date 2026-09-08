from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


class HomepageIntroTests(TestCase):
    browser_headers = {"HTTP_ACCEPT": "text/html,application/xhtml+xml"}

    def test_fresh_home_renders_without_server_redirect_or_intro_session(self):
        response = self.client.get(reverse("core:home"), **self.browser_headers)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "home.html")
        self.assertNotIn("home_intro_seen", self.client.session)
        self.assertFalse(response.wsgi_request.session.modified)

    def test_legacy_session_values_have_no_effect_on_home_or_intro(self):
        for value in (False, True):
            with self.subTest(legacy_flag=value):
                session = self.client.session
                session["home_intro_seen"] = value
                session["unrelated"] = "preserved"
                session.save()
                for url in ("/", "/intro/", "/intro/?preview=1"):
                    response = self.client.get(url, **self.browser_headers)
                    self.assertEqual(response.status_code, 200)
                    self.assertFalse(response.wsgi_request.session.modified)
                self.assertEqual(self.client.session["home_intro_seen"], value)
                self.assertEqual(self.client.session["unrelated"], "preserved")

    def test_guard_precedes_stylesheets_and_body_and_is_home_only(self):
        response = self.client.get(reverse("core:home"))
        html = response.content.decode()
        guard = html.index('sessionStorage.getItem("dd_intro_returning")')
        self.assertLess(guard, html.index('<link rel="stylesheet"'))
        self.assertLess(guard, html.index("<body"))
        response = self.client.get(reverse("accounts:login"))
        self.assertNotContains(response, "dd-intro-pending")

    def test_intro_is_standalone_and_does_not_modify_session(self):
        response = self.client.get(reverse("core:intro"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "intro.html")
        self.assertTemplateNotUsed(response, "base.html")
        self.assertContains(response, 'data-preview="false"')
        self.assertContains(response, 'content="3.5;url=/"')
        self.assertContains(response, "const INTRO_DURATION = 3500;")
        self.assertNotIn("home_intro_seen", self.client.session)
        self.assertFalse(response.wsgi_request.session.modified)

    def test_preview_still_renders_full_intro(self):
        response = self.client.get(f'{reverse("core:intro")}?preview=1')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-preview="true"')
        self.assertTrue(response.context["intro_full_motion"])
        self.assertFalse(response.wsgi_request.session.modified)

    @override_settings(DEBUG=True)
    def test_debug_helpers_replay_intro_without_modifying_session(self):
        for url, destination in (
            ("/intro/reset/", "/intro/"),
            ("/?intro=1", "/intro/?preview=1"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(response, destination, fetch_redirect_response=False)
                self.assertFalse(response.wsgi_request.session.modified)

    @override_settings(DEBUG=False)
    def test_production_helpers(self):
        self.assertEqual(self.client.get("/intro/reset/").status_code, 404)
        response = self.client.get("/?intro=1", **self.browser_headers)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "home.html")

    def test_existing_reduced_motion_policy_and_no_cache_are_preserved(self):
        for debug, preview, expected in (
            (True, False, True), (True, True, True),
            (False, False, False), (False, True, True),
        ):
            with self.subTest(debug=debug, preview=preview), override_settings(DEBUG=debug):
                response = self.client.get("/intro/", {"preview": "1"} if preview else {})
                self.assertEqual(response.context["intro_full_motion"], expected)
                self.assertEqual(response.context["intro_debug_motion"], debug)
                body_class = "intro-page intro-debug-motion" if debug else "intro-page"
                self.assertContains(response, f'class="{body_class}"')
                self.assertContains(response, 'class="intro-particle"', count=30)
                self.assertIn("no-store", response.headers["Cache-Control"])

    @override_settings(DEBUG=True)
    def test_authentication_survives_intro_home_and_debug_helpers(self):
        user = get_user_model().objects.create_user(
            username="intro-reader", email="intro-reader@example.com",
        )
        self.client.force_login(user)
        session_key = self.client.session.session_key
        for url in ("/", "/intro/", "/intro/?preview=1", "/intro/reset/", "/?intro=1", "/"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.wsgi_request.user.pk, user.pk)
                self.assertEqual(self.client.session.session_key, session_key)
                self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
                self.assertFalse(response.wsgi_request.session.modified)
