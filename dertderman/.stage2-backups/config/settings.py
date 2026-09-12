import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent

# Local development may use dertderman/.env. Production can inject the same
# values as real environment variables without creating a .env file.
load_dotenv(BASE_DIR / ".env")


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = "dev-only-dertderman-secret-key-replace-before-production-2026"

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]


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


# Mail transport configuration. Business rules and token generation do not
# belong here; these values only configure the provider-neutral email service.
EMAIL_PROVIDER = (os.getenv("EMAIL_PROVIDER", "resend") or "resend").strip().lower()
EMAIL_SENDING_ENABLED = _env_bool("EMAIL_SENDING_ENABLED", default=False)
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()

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
SITE_BASE_URL = os.getenv(
    "SITE_BASE_URL",
    "http://127.0.0.1:8000",
).strip().rstrip("/")
