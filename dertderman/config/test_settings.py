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
        "POSTGRES_DB": "dertderman_settings_test",
        "POSTGRES_USER": "dertderman_settings_test",
        "POSTGRES_PASSWORD": (
            "settings-test-only-db-password"
        ),
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": "5432",
        "REDIS_URL": "redis://127.0.0.1:6379/0",
        "DJANGO_STATIC_ROOT": str(
            PROJECT_ROOT
            / "_settings-test-static"
        ),
        "DJANGO_MEDIA_ROOT": str(
            PROJECT_ROOT
            / "_settings-test-media"
        ),
    }
    isolated_keys = {
        "DJANGO_ENV",
        "DJANGO_LOG_LEVEL",
        "DJANGO_SECRET_KEY",
        "DJANGO_SECRET_KEY_FILE",
        "DJANGO_ALLOWED_HOSTS",
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "DJANGO_SECURE_HSTS_SECONDS",
        "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
        "DJANGO_SECURE_HSTS_PRELOAD",
        "DJANGO_TRUST_X_FORWARDED_PROTO",
        "DJANGO_SESSION_COOKIE_AGE",
        "DJANGO_AUTH_SESSION_SECURITY_ENABLED",
        "DJANGO_SESSION_ACTIVITY_TOUCH_SECONDS",
        "DJANGO_AUTH_SESSION_REAUTH_MAX_AGE_SECONDS",
        "DJANGO_USER_SESSION_IDLE_SECONDS",
        "DJANGO_USER_SESSION_ABSOLUTE_SECONDS",
        "DJANGO_COMPANY_SESSION_IDLE_SECONDS",
        "DJANGO_COMPANY_SESSION_ABSOLUTE_SECONDS",
        "DJANGO_ADMIN_SESSION_IDLE_SECONDS",
        "DJANGO_ADMIN_SESSION_ABSOLUTE_SECONDS",
        "DJANGO_USER_MAX_ACTIVE_SESSIONS",
        "DJANGO_COMPANY_MAX_ACTIVE_SESSIONS",
        "DJANGO_ADMIN_MAX_ACTIVE_SESSIONS",
        "EMAIL_PROVIDER",
        "EMAIL_SENDING_ENABLED",
        "EMAIL_CHANGE_TIMEOUT",
        "EMAIL_VERIFICATION_TIMEOUT",
        "EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS",
        "PASSWORD_RESET_TIMEOUT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_PASSWORD_FILE",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_CONN_MAX_AGE",
        "POSTGRES_CONNECT_TIMEOUT",
        "REDIS_URL",
        "DJANGO_STATIC_ROOT",
        "DJANGO_MEDIA_ROOT",
        "RESEND_API_KEY",
        "RESEND_TIMEOUT_SECONDS",
        "RESEND_WEBHOOK_MAX_BODY_BYTES",
        "RESEND_WEBHOOK_SECRET",
        "SITE_BASE_URL",
        "SENTRY_ENABLED",
        "SENTRY_DSN",
        "SENTRY_ENVIRONMENT",
        "SENTRY_RELEASE",
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
            "assert settings.SECURE_SSL_REDIRECT is False; "
            "assert settings.DATABASES['default']['ENGINE'] == "
            "'django.db.backends.postgresql'; "
            "assert settings.DATABASES['default']['NAME'] == "
            "'dertderman'; "
            "assert settings.DATABASES['default']['HOST'] == "
            "'127.0.0.1'; "
            "assert settings.CACHES['default']['BACKEND'] == "
            "'django.core.cache.backends.redis.RedisCache'; "
            "assert settings.CACHES['default']['LOCATION'] == "
            "'redis://127.0.0.1:6379/0'",
            env={"DJANGO_ENV": "development"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_requires_storage_roots(self):
        for setting_name in (
            "DJANGO_STATIC_ROOT",
            "DJANGO_MEDIA_ROOT",
        ):
            with self.subTest(
                setting_name=setting_name
            ):
                result = self.run_settings(
                    "import config.settings",
                    env=self.production_env,
                    omitted={setting_name},
                )

                self.assert_configuration_error(
                    result,
                    setting_name,
                )

    def test_production_storage_roots_must_be_absolute_and_separate(self):
        for setting_name in (
            "DJANGO_STATIC_ROOT",
            "DJANGO_MEDIA_ROOT",
        ):
            with self.subTest(
                setting_name=setting_name
            ):
                env = {
                    **self.production_env,
                    setting_name:
                        "relative/storage/path",
                }

                result = self.run_settings(
                    "import config.settings",
                    env=env,
                )

                self.assert_configuration_error(
                    result,
                    setting_name,
                )

        shared_path = str(
            PROJECT_ROOT
            / "_settings-overlap"
        )

        env = {
            **self.production_env,
            "DJANGO_STATIC_ROOT":
                shared_path,
            "DJANGO_MEDIA_ROOT":
                shared_path,
        }

        result = self.run_settings(
            "import config.settings",
            env=env,
        )

        self.assert_configuration_error(
            result,
            "DJANGO_MEDIA_ROOT",
        )

    def test_storage_profiles_are_explicit_and_safe(self):
        development = self.run_settings(
            """
from config import settings

assert settings.STATIC_URL == "/static/"
assert settings.MEDIA_URL == "/media/"
assert settings.STATIC_ROOT == settings.BASE_DIR / "staticfiles"
assert settings.MEDIA_ROOT == settings.BASE_DIR / "media"
assert settings.STORAGES["staticfiles"]["BACKEND"] == (
    "django.contrib.staticfiles.storage.StaticFilesStorage"
)
""",
            env={
                "DJANGO_ENV": "development",
            },
        )

        self.assertEqual(
            development.returncode,
            0,
            development.stderr,
        )

        production = self.run_settings(
            """
from config import settings

assert settings.STATIC_URL == "/static/"
assert settings.MEDIA_URL == "/media/"
assert settings.STATIC_ROOT.is_absolute()
assert settings.MEDIA_ROOT.is_absolute()
assert settings.STATIC_ROOT != settings.MEDIA_ROOT
assert settings.STORAGES["default"]["BACKEND"] == (
    "django.core.files.storage.FileSystemStorage"
)
assert settings.STORAGES["staticfiles"]["BACKEND"] == (
    "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
)
assert settings.FILE_UPLOAD_MAX_MEMORY_SIZE == 1024 * 1024
assert settings.DATA_UPLOAD_MAX_MEMORY_SIZE == 2 * 1024 * 1024
assert settings.DATA_UPLOAD_MAX_NUMBER_FILES == 4
""",
            env=self.production_env,
        )

        self.assertEqual(
            production.returncode,
            0,
            production.stderr,
        )

    def test_production_requires_postgresql_and_redis(self):
        required_settings = (
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_HOST",
            "REDIS_URL",
        )

        for missing_setting in required_settings:
            with self.subTest(
                missing_setting=missing_setting
            ):
                result = self.run_settings(
                    "import config.settings",
                    env=self.production_env,
                    omitted={missing_setting},
                )
                self.assert_configuration_error(
                    result,
                    missing_setting,
                )

    def test_valid_production_profile_uses_postgresql_and_redis(self):
        code = """
import json
from config import settings

database = settings.DATABASES["default"]
cache = settings.CACHES["default"]

print(json.dumps({
    "database_engine": database["ENGINE"],
    "database_name": database["NAME"],
    "database_host": database["HOST"],
    "database_port": database["PORT"],
    "conn_max_age": database["CONN_MAX_AGE"],
    "conn_health_checks": database["CONN_HEALTH_CHECKS"],
    "connect_timeout": database["OPTIONS"]["connect_timeout"],
    "cache_backend": cache["BACKEND"],
    "cache_location": cache["LOCATION"],
}))
"""

        result = self.run_settings(
            code,
            env=self.production_env,
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        values = json.loads(result.stdout)

        self.assertEqual(
            values["database_engine"],
            "django.db.backends.postgresql",
        )
        self.assertEqual(
            values["database_name"],
            "dertderman_settings_test",
        )
        self.assertEqual(
            values["database_host"],
            "127.0.0.1",
        )
        self.assertEqual(
            values["database_port"],
            "5432",
        )
        self.assertEqual(
            values["conn_max_age"],
            60,
        )
        self.assertIs(
            values["conn_health_checks"],
            True,
        )
        self.assertEqual(
            values["connect_timeout"],
            5,
        )
        self.assertEqual(
            values["cache_backend"],
            (
                "django.core.cache.backends.redis."
                "RedisCache"
            ),
        )
        self.assertEqual(
            values["cache_location"],
            "redis://127.0.0.1:6379/0",
        )

    def test_production_rejects_invalid_redis_url(self):
        for invalid_url in (
            "http://127.0.0.1:6379",
            "redis://",
            "not-a-url",
            "redis://127.0.0.1:bad",
            "redis://127.0.0.1:6379/0 bad",
        ):
            with self.subTest(
                invalid_url=invalid_url
            ):
                env = {
                    **self.production_env,
                    "REDIS_URL": invalid_url,
                }
                result = self.run_settings(
                    "import config.settings",
                    env=env,
                )
                self.assert_configuration_error(
                    result,
                    "REDIS_URL",
                )

    def test_production_rejects_invalid_postgres_numeric_settings(self):
        invalid_cases = (
            ("POSTGRES_PORT", "0"),
            ("POSTGRES_PORT", "-1"),
            ("POSTGRES_PORT", "invalid"),
            ("POSTGRES_CONN_MAX_AGE", "-1"),
            ("POSTGRES_CONN_MAX_AGE", "invalid"),
            ("POSTGRES_CONNECT_TIMEOUT", "0"),
            ("POSTGRES_CONNECT_TIMEOUT", "-1"),
            ("POSTGRES_CONNECT_TIMEOUT", "invalid"),
        )

        for setting_name, invalid_value in invalid_cases:
            with self.subTest(
                setting_name=setting_name,
                invalid_value=invalid_value,
            ):
                env = {
                    **self.production_env,
                    setting_name: invalid_value,
                }
                result = self.run_settings(
                    "import config.settings",
                    env=env,
                )
                self.assert_configuration_error(
                    result,
                    setting_name,
                )

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

    def test_production_rejects_weak_secret_keys(self):
        invalid_secrets = (
            "too-short",
            "a" * 49,
            "dev-only-" + ("x" * 60),
            "django-insecure-" + ("x" * 60),
        )

        for secret in invalid_secrets:
            with self.subTest(secret_prefix=secret[:16]):
                env = {
                    **self.production_env,
                    "DJANGO_SECRET_KEY": secret,
                }
                result = self.run_settings(
                    "import config.settings",
                    env=env,
                )
                self.assert_configuration_error(
                    result,
                    "DJANGO_SECRET_KEY",
                )

    def test_production_session_security_profile(self):
        code = """
from config import settings

assert settings.SESSION_COOKIE_NAME == "__Host-dd_session"
assert settings.CSRF_COOKIE_NAME == "__Host-dd_csrf"

assert settings.SESSION_COOKIE_SECURE is True
assert settings.CSRF_COOKIE_SECURE is True
assert settings.SESSION_COOKIE_HTTPONLY is True
assert settings.CSRF_COOKIE_HTTPONLY is True

assert settings.SESSION_COOKIE_PATH == "/"
assert settings.CSRF_COOKIE_PATH == "/"
assert settings.SESSION_COOKIE_DOMAIN is None
assert settings.CSRF_COOKIE_DOMAIN is None

assert settings.SESSION_COOKIE_SAMESITE == "Lax"
assert settings.CSRF_COOKIE_SAMESITE == "Lax"

assert settings.SESSION_COOKIE_AGE == 28800
assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is True
assert settings.SESSION_SAVE_EVERY_REQUEST is False

assert settings.AUTH_SESSION_SECURITY_ENABLED is True
assert settings.AUTH_SESSION_ACTIVITY_TOUCH_SECONDS == 60
assert settings.AUTH_SESSION_REAUTH_MAX_AGE_SECONDS == 300

assert settings.AUTH_SESSION_SECURITY_POLICIES["USER"] == {
    "idle_seconds": 28800,
    "absolute_seconds": 28800,
}

assert settings.AUTH_SESSION_SECURITY_POLICIES["COMPANY"] == {
    "idle_seconds": 7200,
    "absolute_seconds": 28800,
}

assert settings.AUTH_SESSION_SECURITY_POLICIES["ADMIN"] == {
    "idle_seconds": 1800,
    "absolute_seconds": 14400,
}

assert settings.AUTH_SESSION_MAX_ACTIVE_SESSIONS == {
    "USER": 5,
    "COMPANY": 3,
    "ADMIN": 2,
}

assert settings.USE_X_FORWARDED_HOST is False
assert settings.USE_X_FORWARDED_PORT is False

assert settings.SECURE_REFERRER_POLICY == "same-origin"
assert settings.SECURE_CROSS_ORIGIN_OPENER_POLICY == "same-origin"
assert settings.X_FRAME_OPTIONS == "DENY"
"""
        result = self.run_settings(
            code,
            env=self.production_env,
        )
        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

    def test_production_session_cookie_age_must_be_positive(self):
        for invalid_value in (
            "0",
            "-1",
            "invalid",
            "1.5",
        ):
            with self.subTest(
                invalid_value=invalid_value
            ):
                env = {
                    **self.production_env,
                    "DJANGO_SESSION_COOKIE_AGE":
                        invalid_value,
                }

                result = self.run_settings(
                    "import config.settings",
                    env=env,
                )

                self.assert_configuration_error(
                    result,
                    "DJANGO_SESSION_COOKIE_AGE",
                )

    def test_production_password_hashing_prefers_argon2_and_accepts_pbkdf2(self):
        code = """
from django.contrib.auth.hashers import (
    PBKDF2PasswordHasher,
    check_password,
    identify_hasher,
    make_password,
)

password = "SecurityRegressionPassword2026!"

encoded = make_password(password)
assert identify_hasher(encoded).algorithm == "argon2"
assert check_password(password, encoded)

legacy = PBKDF2PasswordHasher().encode(
    password,
    "fixed-test-salt",
)
assert identify_hasher(legacy).algorithm == "pbkdf2_sha256"
assert check_password(password, legacy)
"""

        result = self.run_settings(
            code,
            env=self.production_env,
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
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
        secret = (
            "never-expose-this-settings-test-secret-"
            + ("x" * 32)
        )
        env = {**self.production_env, "DJANGO_SECRET_KEY": secret}
        result = self.run_settings(
            "import config.settings",
            env=env,
            omitted={"DJANGO_ALLOWED_HOSTS"},
        )
        self.assert_configuration_error(result, "DJANGO_ALLOWED_HOSTS")
        self.assertNotIn(secret, result.stdout + result.stderr)

    def test_resend_timeout_must_be_a_positive_integer(self):
        for invalid_value in ("0", "-1", "1.5", "invalid"):
            with self.subTest(invalid_value=invalid_value):
                env = {
                    **self.production_env,
                    "RESEND_TIMEOUT_SECONDS": invalid_value,
                }
                result = self.run_settings("import config.settings", env=env)
                self.assert_configuration_error(result, "RESEND_TIMEOUT_SECONDS")

    def test_resend_webhook_body_limit_must_be_a_positive_integer(self):
        for invalid_value in ("0", "-1", "1.5", "invalid"):
            with self.subTest(invalid_value=invalid_value):
                env = {
                    **self.production_env,
                    "RESEND_WEBHOOK_MAX_BODY_BYTES": invalid_value,
                }
                result = self.run_settings("import config.settings", env=env)
                self.assert_configuration_error(
                    result,
                    "RESEND_WEBHOOK_MAX_BODY_BYTES",
                )

    def test_email_sending_enabled_must_be_a_boolean(self):
        env = {
            **self.production_env,
            "EMAIL_SENDING_ENABLED": "sometimes",
        }
        result = self.run_settings("import config.settings", env=env)
        self.assert_configuration_error(result, "EMAIL_SENDING_ENABLED")

    def test_enabled_production_resend_requires_transport_and_webhook_secrets(self):
        configured_env = {
            **self.production_env,
            "EMAIL_PROVIDER": "resend",
            "EMAIL_SENDING_ENABLED": "True",
            "RESEND_API_KEY": "re_settings_test_only",
            "RESEND_WEBHOOK_SECRET": "whsec_settings_test_only",
        }
        valid_result = self.run_settings(
            "import config.settings",
            env=configured_env,
        )
        self.assertEqual(valid_result.returncode, 0, valid_result.stderr)

        for missing_setting in ("RESEND_API_KEY", "RESEND_WEBHOOK_SECRET"):
            with self.subTest(missing_setting=missing_setting):
                result = self.run_settings(
                    "import config.settings",
                    env=configured_env,
                    omitted={missing_setting},
                )
                self.assert_configuration_error(result, missing_setting)

    def test_enabled_production_email_rejects_unsupported_provider(self):
        env = {
            **self.production_env,
            "EMAIL_PROVIDER": "unsupported",
            "EMAIL_SENDING_ENABLED": "True",
            "RESEND_API_KEY": "re_settings_test_only",
            "RESEND_WEBHOOK_SECRET": "whsec_settings_test_only",
        }
        result = self.run_settings("import config.settings", env=env)
        self.assert_configuration_error(result, "EMAIL_PROVIDER")

    def test_disabled_production_email_does_not_require_resend_secrets(self):
        env = {
            **self.production_env,
            "EMAIL_PROVIDER": "resend",
            "EMAIL_SENDING_ENABLED": "False",
        }
        result = self.run_settings(
            "from config import settings; "
            "assert settings.EMAIL_SENDING_ENABLED is False; "
            "assert settings.RESEND_API_KEY == ''; "
            "assert settings.RESEND_WEBHOOK_SECRET == ''",
            env=env,
            omitted={"RESEND_API_KEY", "RESEND_WEBHOOK_SECRET"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_email_verification_timeout_must_be_a_positive_integer(self):
        for invalid_value in ("0", "-1", "1.5", "invalid"):
            with self.subTest(invalid_value=invalid_value):
                env = {
                    **self.production_env,
                    "EMAIL_VERIFICATION_TIMEOUT": invalid_value,
                }
                result = self.run_settings("import config.settings", env=env)
                self.assert_configuration_error(
                    result,
                    "EMAIL_VERIFICATION_TIMEOUT",
                )

    def test_account_security_timeouts_must_be_positive_integers(self):
        for setting_name in ("PASSWORD_RESET_TIMEOUT", "EMAIL_CHANGE_TIMEOUT"):
            for invalid_value in ("0", "-1", "1.5", "invalid"):
                with self.subTest(
                    setting_name=setting_name,
                    invalid_value=invalid_value,
                ):
                    env = {
                        **self.production_env,
                        setting_name: invalid_value,
                    }
                    result = self.run_settings("import config.settings", env=env)
                    self.assert_configuration_error(result, setting_name)

    def test_email_verification_resend_cooldown_must_be_a_positive_integer(self):
        for invalid_value in ("0", "-1", "1.5", "invalid"):
            with self.subTest(invalid_value=invalid_value):
                env = {
                    **self.production_env,
                    "EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS": invalid_value,
                }
                result = self.run_settings("import config.settings", env=env)
                self.assert_configuration_error(
                    result,
                    "EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS",
                )

    def test_production_logging_uses_stdout_and_safe_levels(
        self,
    ):
        code = """
from config import settings

assert settings.APP_LOG_LEVEL == "INFO"

logging_config = settings.LOGGING

assert (
    logging_config["handlers"]["console"]["stream"]
    == "ext://sys.stdout"
)

assert (
    logging_config["root"]["level"]
    == "INFO"
)

assert (
    logging_config["loggers"]["django.request"]["level"]
    == "WARNING"
)

assert (
    logging_config["loggers"]["django.security"]["level"]
    == "WARNING"
)

assert (
    logging_config["loggers"]["django.db.backends"]["level"]
    == "WARNING"
)

assert (
    logging_config["loggers"]["httpx"]["level"]
    == "WARNING"
)

assert (
    logging_config["loggers"]["httpcore"]["level"]
    == "WARNING"
)

assert (
    logging_config["loggers"]["urllib3"]["level"]
    == "WARNING"
)
"""

        result = self.run_settings(
            code,
            env=self.production_env,
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

    def test_production_log_level_is_configurable_without_enabling_sql_debug(
        self,
    ):
        env = {
            **self.production_env,
            "DJANGO_LOG_LEVEL":
                "DEBUG",
        }

        code = """
from config import settings

assert settings.APP_LOG_LEVEL == "DEBUG"
assert settings.LOGGING["root"]["level"] == "DEBUG"

assert (
    settings.LOGGING[
        "loggers"
    ][
        "django.db.backends"
    ][
        "level"
    ]
    == "WARNING"
)
"""

        result = self.run_settings(
            code,
            env=env,
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

    def test_production_rejects_invalid_log_level(
        self,
    ):
        env = {
            **self.production_env,
            "DJANGO_LOG_LEVEL":
                "VERBOSE",
        }

        result = self.run_settings(
            "import config.settings",
            env=env,
        )

        self.assert_configuration_error(
            result,
            "DJANGO_LOG_LEVEL",
        )


    def test_framework_request_logs_use_sanitizing_handler(
        self,
    ):
        code = """
from config import settings

config = settings.LOGGING

assert (
    "safe_framework_request"
    in config["filters"]
)

assert (
    config["loggers"][
        "django.request"
    ]["handlers"]
    == ["safe_framework_console"]
)

assert (
    config["loggers"][
        "django.security"
    ]["handlers"]
    == ["safe_framework_console"]
)
"""

        result = self.run_settings(
            code,
            env=self.production_env,
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )


    def test_framework_request_logs_use_sanitizing_handler(
        self,
    ):
        code = """
from config import settings

config = settings.LOGGING

assert (
    "safe_framework_request"
    in config["filters"]
)

assert (
    config["loggers"][
        "django.request"
    ]["handlers"]
    == ["safe_framework_console"]
)

assert (
    config["loggers"][
        "django.security"
    ]["handlers"]
    == ["safe_framework_console"]
)
"""

        result = self.run_settings(
            code,
            env=self.production_env,
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )


    def test_sentry_is_disabled_by_default(
        self,
    ):
        code = """
from config import settings
import sentry_sdk

assert settings.SENTRY_ENABLED is False
assert settings.SENTRY_DSN == ""
assert sentry_sdk.is_initialized() is False
"""

        result = self.run_settings(
            code,
            env=self.production_env,
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

    def test_sentry_enabled_requires_dsn(
        self,
    ):
        env = {
            **self.production_env,
            "SENTRY_ENABLED":
                "True",
        }

        result = self.run_settings(
            "import config.settings",
            env=env,
            omitted={
                "SENTRY_DSN",
            },
        )

        self.assert_configuration_error(
            result,
            "SENTRY_DSN",
        )

    def test_sentry_cannot_be_enabled_in_development(
        self,
    ):
        result = self.run_settings(
            "import config.settings",
            env={
                "DJANGO_ENV":
                    "development",

                "SENTRY_ENABLED":
                    "True",

                "SENTRY_DSN":
                    (
                        "https://public-key@"
                        "sentry.example/1"
                    ),
            },
        )

        self.assert_configuration_error(
            result,
            "SENTRY_ENABLED",
        )

    def test_valid_production_sentry_profile_initializes_client(
        self,
    ):
        env = {
            **self.production_env,

            "SENTRY_ENABLED":
                "True",

            "SENTRY_DSN":
                (
                    "https://public-key@"
                    "sentry.example/1"
                ),

            "SENTRY_ENVIRONMENT":
                "production",

            "SENTRY_RELEASE":
                "stage5-test",
        }

        code = """
from config import settings
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

client = sentry_sdk.get_client()

assert settings.SENTRY_ENABLED is True
assert sentry_sdk.is_initialized() is True
assert client.is_active() is True

assert client.options["send_default_pii"] is False
assert client.options["max_request_body_size"] == "never"
assert client.options["include_local_variables"] is False
assert client.options["include_source_context"] is False

assert client.options["enable_logs"] is False
assert client.options["enable_tracing"] is False
assert client.options["propagate_traces"] is False
assert client.options["trace_propagation_targets"] == []

assert client.options["traces_sample_rate"] == 0.0
assert client.options["profiles_sample_rate"] == 0.0

assert client.options["environment"] == "production"
assert client.options["release"] == "stage5-test"

assert client.get_integration(LoggingIntegration) is None
"""

        result = self.run_settings(
            code,
            env=env,
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )
