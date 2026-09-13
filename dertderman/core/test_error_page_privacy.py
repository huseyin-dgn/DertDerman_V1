from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase


class ErrorPagePrivacyTests(SimpleTestCase):
    templates = (
        "400.html",
        "403.html",
        "404.html",
        "500.html",
        "csrf_failure.html",
    )

    def test_error_pages_do_not_reflect_request_path_in_seo_metadata(self):
        request = RequestFactory().get("/private-secret-marker/")
        request.user = AnonymousUser()

        for template_name in self.templates:
            with self.subTest(template=template_name):
                html = render_to_string(template_name, request=request)

                self.assertNotIn("private-secret-marker", html)
                self.assertNotIn('rel="canonical"', html)
                self.assertNotIn('property="og:url"', html)
                self.assertIn(
                    'name="robots" content="noindex, nofollow"',
                    html,
                )
