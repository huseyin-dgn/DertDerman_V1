from django.contrib.auth import get_user_model
from django.core.exceptions import SuspiciousOperation
from django.test import Client, TestCase, override_settings
from django.urls import clear_url_caches, include, path, reverse
from django.views.static import serve

from companies.models import Company


def server_failure(request):
    raise RuntimeError("INTERNAL-TEST-SECRET /private/server/path database failure")


def bad_request(request):
    raise SuspiciousOperation("INTERNAL-TEST-SECRET token=hidden")


urlpatterns = [
    path("test-failure/", server_failure),
    path("test-bad-request/", bad_request),
    path("", include("config.urls")),
]


User = get_user_model()


class FeedbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="feedback-user", email="feedback@example.com",
            password="FeedbackPassword2026!", user_type="USER",
        )
        cls.company = Company.objects.create(name="Feedback Company")

    def setUp(self):
        self.client.force_login(self.user)

    def test_profile_success_is_shown_once(self):
        response = self.client.post(reverse("accounts:profile_edit"), {
            "first_name": "Updated", "last_name": "Name", "email": self.user.email, "phone": "",
        }, follow=True)
        self.assertContains(response, "Profil bilgileriniz güncellendi.", count=1)
        self.assertContains(response, 'data-feedback="success"')
        self.assertContains(response, 'aria-live="polite"')
        self.assertNotContains(self.client.get(reverse("accounts:profile")), "Profil bilgileriniz güncellendi.")

    def test_password_feedback_preserves_authenticated_session(self):
        response = self.client.post(reverse("accounts:password_change"), {
            "old_password": "FeedbackPassword2026!",
            "new_password1": "NewFeedbackPassword2027!", "new_password2": "NewFeedbackPassword2027!",
        }, follow=True)
        self.assertContains(response, "Şifreniz başarıyla güncellendi.")
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewFeedbackPassword2027!"))

    def test_complaint_submission_feedback_and_pending_state(self):
        response = self.client.post(reverse("complaints:create"), {
            "company": self.company.pk, "title": "Feedback complaint",
            "description": "A complaint created to check the submission feedback.",
        }, follow=True)
        self.assertContains(response, "Şikayetiniz incelemeye alındı.")
        self.assertEqual(self.user.complaints.get().status, "PENDING")

    def test_logout_info_without_authentication(self):
        response = self.client.post(reverse("accounts:logout"), follow=True)
        self.assertContains(response, "Oturumunuz güvenli şekilde kapatıldı.")
        self.assertContains(response, 'data-feedback="info"')
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_error_is_generic_for_existing_and_missing_accounts(self):
        self.client.logout()
        for username in [self.user.username, "no-such-account"]:
            response = self.client.post(reverse("accounts:login"), {"username": username, "password": "wrong-password"})
            self.assertContains(response, "Giriş bilgileriniz doğrulanamadı. Kullanıcı adınızı ve şifrenizi kontrol edin.")
            self.assertContains(response, 'role="alert"')
            self.assertNotContains(response, "Kullanıcı adı bulunamadı")
            self.assertNotContains(response, self.user.email)
            self.assertNotContains(response, "wrong-password")

    def test_field_errors_are_associated_and_success_is_not_shown_on_failure(self):
        response = self.client.post(reverse("accounts:profile_edit"), {"email": "invalid-address"})
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, 'id="id_email_error"')
        self.assertContains(response, 'aria-describedby="id_email_error"')
        self.assertNotContains(response, 'data-feedback="success"')

    @override_settings(DEBUG=False, ROOT_URLCONF=__name__)
    def test_production_error_templates_do_not_expose_details(self):
        cases = [
            ("/yonetim/", 403, "403.html", "Bu alana erişim yetkiniz bulunmuyor."),
            ("/missing-private-url/", 404, "404.html", "Aradığınız sayfayı bulamadık."),
            ("/test-failure/", 500, "500.html", "Bir şeyler yolunda gitmedi."),
            ("/test-bad-request/", 400, "400.html", "İsteğinizi tamamlayamadık."),
        ]
        self.client.raise_request_exception = False
        for url, code, template, message in cases:
            with self.subTest(code=code):
                response = self.client.get(url)
                self.assertEqual(response.status_code, code)
                self.assertTemplateUsed(response, template)
                self.assertContains(response, message, status_code=code)
                for secret in ["INTERNAL-TEST-SECRET", "/private/server/path", "database failure", "Traceback", "missing-private-url", "token=hidden"]:
                    self.assertNotContains(response, secret, status_code=code)

    def test_custom_404_in_both_debug_modes_preserves_real_and_media_routes(self):
        from config import urls as urlconf

        # URL patterns capture DEBUG and MEDIA_ROOT at import time.
        try:
            with TemporaryDirectory() as media_root:
                Path(media_root, "route-check.txt").write_bytes(b"development media")
                for debug in [True, False]:
                    with override_settings(DEBUG=debug, MEDIA_ROOT=media_root, ROOT_URLCONF="config.urls"):
                        reload(urlconf)
                        clear_url_caches()
                        client = Client()
                        for url in ["/312", "/olmayan-bir-url/", "/django-admin/"]:
                            with self.subTest(debug=debug, url=url):
                                response = client.get(url)
                                self.assertEqual(response.status_code, 404)
                                self.assertTemplateUsed(response, "404.html")
                                self.assertContains(response, "Aradığınız sayfayı bulamadık.", status_code=404)
                                self.assertNotContains(response, "DEBUG = True", status_code=404)
                                self.assertEqual(response.resolver_match.url_name, "custom_404")
                        for url in ["/", "/hesap/giris/", "/blog/", "/sikayetler/"]:
                            with self.subTest(debug=debug, real_url=url):
                                response = client.get(url)
                                self.assertEqual(response.status_code, 200)
                                self.assertTemplateNotUsed(response, "404.html")
                                self.assertNotEqual(response.resolver_match.url_name, "custom_404")
                        self.assertRedirects(client.get("/panel/"), "/hesap/giris/?next=/panel/")
                        client.force_login(self.user)
                        response = client.get("/panel/")
                        self.assertEqual(response.status_code, 200)
                        self.assertIn("no-store", response["Cache-Control"])
                        response = client.get("/media/route-check.txt")
                        if debug:
                            self.assertEqual(response.status_code, 200)
                            self.assertIs(response.resolver_match.func, serve)
                            self.assertEqual(b"".join(response.streaming_content), b"development media")
                            response.close()
                        else:
                            self.assertEqual(response.status_code, 404)
                            self.assertTemplateUsed(response, "404.html")
        finally:
            reload(urlconf)
            clear_url_caches()

    @override_settings(DEBUG=False)
    def test_csrf_error_is_branded_and_remains_forbidden(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(reverse("accounts:profile_edit"), {"email": "changed@example.com"})
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "csrf_failure.html")
        self.assertContains(response, "İşleminizin süresi dolmuş olabilir.", status_code=403)
        self.assertNotContains(response, "CSRF cookie not set", status_code=403)
        self.assertIn("no-store", response["Cache-Control"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "feedback@example.com")
from importlib import reload
from pathlib import Path
from tempfile import TemporaryDirectory
