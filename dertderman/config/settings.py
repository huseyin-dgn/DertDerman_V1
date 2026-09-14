import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent

# The deployment profile itself must be supplied by the process environment.
# Local development keeps loading dertderman/.env; production reads only its
# injected environment and cannot accidentally inherit local development data.
DJANGO_ENV = (os.getenv("DJANGO_ENV", "development") or "").strip().lower()
if DJANGO_ENV not in {"development", "production"}:
    raise ImproperlyConfigured(
        "DJANGO_ENV must be either 'development' or 'production'."
    )

IS_PRODUCTION = DJANGO_ENV == "production"

if not IS_PRODUCTION:
    load_dotenv(BASE_DIR / ".env")


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _required_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"{name} is required in production.")
    return value


def _env_csv(name, *, required=False):
    raw_value = os.getenv(name, "")
    values = [value.strip() for value in raw_value.split(",") if value.strip()]
    if required and not values:
        raise ImproperlyConfigured(f"{name} is required in production.")
    if any("*" in value for value in values):
        raise ImproperlyConfigured(f"{name} must not contain wildcard entries.")
    return values


def _strict_env_bool(name, *, default=False):
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean value.")


def _nonnegative_env_int(name, *, default=0):
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"{name} must be a non-negative integer."
        ) from exc
    if value < 0:
        raise ImproperlyConfigured(f"{name} must be a non-negative integer.")
    return value


def _positive_env_int(name, *, default):
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise ImproperlyConfigured(f"{name} must be a positive integer.")
    return value


def _validate_https_origin(origin, *, setting_name):
    try:
        parsed = urlsplit(origin)
        parsed.port
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"{setting_name} must contain valid HTTPS origins."
        ) from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or any(character.isspace() for character in origin)
    ):
        raise ImproperlyConfigured(
            f"{setting_name} must contain valid HTTPS origins."
        )


def _production_site_base_url():
    value = _required_env("SITE_BASE_URL").rstrip("/")
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError as exc:
        raise ImproperlyConfigured(
            "SITE_BASE_URL must be a valid absolute HTTPS URL."
        ) from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or any(character.isspace() for character in value)
    ):
        raise ImproperlyConfigured(
            "SITE_BASE_URL must be a valid absolute HTTPS URL without "
            "userinfo, query, or fragment components."
        )
    return value


if IS_PRODUCTION:
    SECRET_KEY = _required_env("DJANGO_SECRET_KEY")
    DEBUG = False
    ALLOWED_HOSTS = _env_csv("DJANGO_ALLOWED_HOSTS", required=True)
    CSRF_TRUSTED_ORIGINS = _env_csv("DJANGO_CSRF_TRUSTED_ORIGINS")
    for trusted_origin in CSRF_TRUSTED_ORIGINS:
        _validate_https_origin(
            trusted_origin,
            setting_name="DJANGO_CSRF_TRUSTED_ORIGINS",
        )
else:
    SECRET_KEY = "dev-only-dertderman-secret-key-replace-before-production-2026"
    DEBUG = True
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]
    CSRF_TRUSTED_ORIGINS = []


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts.apps.AccountsConfig",
    "companies.apps.CompaniesConfig",
    "complaints.apps.ComplaintsConfig",
    "payments.apps.PaymentsConfig",
    "notifications.apps.NotificationsConfig",
    "blog.apps.BlogConfig",
    "dashboard.apps.DashboardConfig",
    "adminx.apps.AdminxConfig",
    "core.apps.CoreConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "adminx.context_processors.admin_shell",
                "notifications.context_processors.notification_badge",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Stage 1 intentionally preserves the existing SQLite configuration. It is not
# a production database design; an external production database remains a
# deployment blocker to resolve in a later stage.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


LANGUAGE_CODE = "tr-tr"

TIME_ZONE = "Europe/Istanbul"

USE_I18N = True

USE_TZ = True


STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "core:home"

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_FAILURE_VIEW = "core.error_views.csrf_failure"

if IS_PRODUCTION:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    TRUST_X_FORWARDED_PROTO = _strict_env_bool(
        "DJANGO_TRUST_X_FORWARDED_PROTO",
        default=False,
    )
    SECURE_PROXY_SSL_HEADER = (
        ("HTTP_X_FORWARDED_PROTO", "https")
        if TRUST_X_FORWARDED_PROTO
        else None
    )
    SECURE_HSTS_SECONDS = _nonnegative_env_int(
        "DJANGO_SECURE_HSTS_SECONDS",
        default=0,
    )
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _strict_env_bool(
        "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
        default=False,
    )
    SECURE_HSTS_PRELOAD = _strict_env_bool(
        "DJANGO_SECURE_HSTS_PRELOAD",
        default=False,
    )
else:
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_SSL_REDIRECT = False
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False


# Mail transport configuration. Business rules and token generation do not
# belong here; these values only configure the provider-neutral email service.
EMAIL_PROVIDER = (os.getenv("EMAIL_PROVIDER", "resend") or "resend").strip().lower()
EMAIL_SENDING_ENABLED = _env_bool("EMAIL_SENDING_ENABLED", default=False)
TRANSACTIONAL_EMAILS_ENABLED = _env_bool(
    "TRANSACTIONAL_EMAILS_ENABLED",
    default=True,
)
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
RESEND_WEBHOOK_SECRET = os.getenv("RESEND_WEBHOOK_SECRET", "").strip()
RESEND_WEBHOOK_MAX_BODY_BYTES = int(
    os.getenv("RESEND_WEBHOOK_MAX_BODY_BYTES", "131072")
)
RESEND_TIMEOUT_SECONDS = _positive_env_int(
    "RESEND_TIMEOUT_SECONDS",
    default=30,
)

DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    "DertDerman <info@dertderman.com>",
).strip()
EMAIL_REPLY_TO = os.getenv(
    "EMAIL_REPLY_TO",
    "destek@dertderman.com",
).strip()
SUPPORT_EMAIL = os.getenv(
    "SUPPORT_EMAIL",
    "destek@dertderman.com",
).strip()
SUPPORT_PHONE = os.getenv(
    "SUPPORT_PHONE",
    "+90 850 532 2206",
).strip()
SUPPORT_HOURS = os.getenv(
    "SUPPORT_HOURS",
    "Hafta içi 09:00 - 18:00",
).strip()
SITE_BASE_URL = (
    _production_site_base_url()
    if IS_PRODUCTION
    else os.getenv("SITE_BASE_URL", "http://127.0.0.1:8000").strip().rstrip("/")
)


# Password-reset links are valid for 5 minutes by default.
PASSWORD_RESET_TIMEOUT = int(
    os.getenv("PASSWORD_RESET_TIMEOUT", "300")
)


# Verification links are valid for 30 minutes by default.
EMAIL_VERIFICATION_TIMEOUT = int(
    os.getenv("EMAIL_VERIFICATION_TIMEOUT", "1800")
)

# Authenticated email-change links are valid for 10 minutes by default.
EMAIL_CHANGE_TIMEOUT = int(
    os.getenv("EMAIL_CHANGE_TIMEOUT", "600")
)


# Stage 7 security throttling.
# Normal çalışmada rate limit varsayılan olarak açıktır.
# Django test suite'inde ise eski/ilişkisiz testlerin aynı test IP'sini
# paylaşması rate-limit bucket'larını birbirine taşımamalıdır.
# Stage 7'nin kendi testleri @override_settings(RATE_LIMIT_ENABLED=True)
# ile rate limiting'i açıkça etkinleştirir.
RUNNING_TESTS = "test" in sys.argv

RATE_LIMIT_ENABLED = _env_bool(
    "RATE_LIMIT_ENABLED",
    default=not RUNNING_TESTS,
)

# Only enable this in production when the origin is restricted to Cloudflare
# or another trusted reverse proxy.
TRUST_CLOUDFLARE_CONNECTING_IP = _env_bool(
    "TRUST_CLOUDFLARE_CONNECTING_IP",
    default=False,
)
