import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class SettingsProfileTests(SimpleTestCase):
    production_env = {
        "DJANGO_ENV": "production",
        "DJANGO_SECRET_KEY": "settings-test-only-secret-with-sufficient-length-1234567890",
        "DJANGO_ALLOWED_HOSTS": "dertderman.example,www.dertderman.example",
        "DJANGO_CSRF_TRUSTED_ORIGINS": (
            "https://dertderman.example,https://www.dertderman.example"
        ),
        "SITE_BASE_URL": "https://dertderman.example",
    }
    isolated_keys = {
        "DJANGO_ENV",
        "DJANGO_SECRET_KEY",
        "DJANGO_ALLOWED_HOSTS",
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "DJANGO_SECURE_HSTS_SECONDS",
        "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
        "DJANGO_SECURE_HSTS_PRELOAD",
        "DJANGO_TRUST_X_FORWARDED_PROTO",
        "SITE_BASE_URL",
    }

    def run_settings(self, code, *, env=None, omitted=()):
        process_env = os.environ.copy()
        for key in self.isolated_keys:
            process_env.pop(key, None)
        process_env.update(env or {})
        for key in omitted:
            process_env.pop(key, None)
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=PROJECT_ROOT,
            env=process_env,
            text=True,
            capture_output=True,
            check=False,
        )

    def assert_configuration_error(self, result, setting_name):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn(setting_name, result.stderr)

    def test_development_profile_opens_with_local_defaults(self):
        result = self.run_settings(
            "from config import settings; "
            "assert settings.DEBUG is True; "
            "assert settings.SECRET_KEY.startswith('dev-only-'); "
            "assert 'localhost' in settings.ALLOWED_HOSTS; "
            "assert settings.SESSION_COOKIE_SECURE is False; "
            "assert settings.SECURE_SSL_REDIRECT is False",
            env={"DJANGO_ENV": "development"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_requires_secret_key(self):
        result = self.run_settings(
            "import config.settings",
            env=self.production_env,
            omitted={"DJANGO_SECRET_KEY"},
        )
        self.assert_configuration_error(result, "DJANGO_SECRET_KEY")

    def test_production_requires_allowed_hosts(self):
        result = self.run_settings(
            "import config.settings",
            env=self.production_env,
            omitted={"DJANGO_ALLOWED_HOSTS"},
        )
        self.assert_configuration_error(result, "DJANGO_ALLOWED_HOSTS")

    def test_production_requires_site_base_url(self):
        result = self.run_settings(
            "import config.settings",
            env=self.production_env,
            omitted={"SITE_BASE_URL"},
        )
        self.assert_configuration_error(result, "SITE_BASE_URL")

    def test_production_rejects_insecure_or_unsafe_site_base_url(self):
        invalid_urls = (
            "http://dertderman.example",
            "https://user@dertderman.example",
            "https://dertderman.example?token=test",
            "https://dertderman.example#fragment",
            "https://dertderman.example/foo",
            "https://dertderman.example/invalid path",
        )
        for invalid_url in invalid_urls:
            with self.subTest(invalid_url=invalid_url):
                env = {**self.production_env, "SITE_BASE_URL": invalid_url}
                result = self.run_settings("import config.settings", env=env)
                self.assert_configuration_error(result, "SITE_BASE_URL")

    def test_valid_production_profile_enables_security_settings(self):
        code = """
import json
from config import settings
print(json.dumps({
    "allowed_hosts": settings.ALLOWED_HOSTS,
    "csrf_cookie_secure": settings.CSRF_COOKIE_SECURE,
    "csrf_trusted_origins": settings.CSRF_TRUSTED_ORIGINS,
    "debug": settings.DEBUG,
    "hsts_seconds": settings.SECURE_HSTS_SECONDS,
    "proxy_header": settings.SECURE_PROXY_SSL_HEADER,
    "session_cookie_secure": settings.SESSION_COOKIE_SECURE,
    "site_base_url": settings.SITE_BASE_URL,
    "ssl_redirect": settings.SECURE_SSL_REDIRECT,
}))
"""
        result = self.run_settings(code, env=self.production_env)
        self.assertEqual(result.returncode, 0, result.stderr)
        settings_values = json.loads(result.stdout)
        self.assertEqual(
            settings_values["allowed_hosts"],
            ["dertderman.example", "www.dertderman.example"],
        )
        self.assertEqual(
            settings_values["csrf_trusted_origins"],
            [
                "https://dertderman.example",
                "https://www.dertderman.example",
            ],
        )
        self.assertIs(settings_values["debug"], False)
        self.assertIs(settings_values["session_cookie_secure"], True)
        self.assertIs(settings_values["csrf_cookie_secure"], True)
        self.assertIs(settings_values["ssl_redirect"], True)
        self.assertIsNone(settings_values["proxy_header"])
        self.assertEqual(settings_values["hsts_seconds"], 0)
        self.assertEqual(
            settings_values["site_base_url"],
            "https://dertderman.example",
        )

    def test_production_can_trust_sanitized_forwarded_proto(self):
        env = {
            **self.production_env,
            "DJANGO_TRUST_X_FORWARDED_PROTO": "True",
        }
        result = self.run_settings(
            "from config import settings; "
            "assert settings.SECURE_PROXY_SSL_HEADER == "
            "('HTTP_X_FORWARDED_PROTO', 'https')",
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_rejects_invalid_forwarded_proto_boolean(self):
        env = {
            **self.production_env,
            "DJANGO_TRUST_X_FORWARDED_PROTO": "sometimes",
        }
        result = self.run_settings("import config.settings", env=env)
        self.assert_configuration_error(
            result,
            "DJANGO_TRUST_X_FORWARDED_PROTO",
        )

    def test_production_configuration_error_does_not_expose_secret(self):
        secret = "never-expose-this-settings-test-secret"
        env = {**self.production_env, "DJANGO_SECRET_KEY": secret}
        result = self.run_settings(
            "import config.settings",
            env=env,
            omitted={"DJANGO_ALLOWED_HOSTS"},
        )
        self.assert_configuration_error(result, "DJANGO_ALLOWED_HOSTS")
        self.assertNotIn(secret, result.stdout + result.stderr)
