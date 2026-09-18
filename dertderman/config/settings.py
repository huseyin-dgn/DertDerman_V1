import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from .validation import validate_site_base_url


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


def _production_secret_key():
    value = _required_env("DJANGO_SECRET_KEY")

    if len(value) < 50:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be at least 50 characters "
            "in production."
        )

    unsafe_prefixes = (
        "dev-only-",
        "django-insecure-",
    )

    if value.startswith(unsafe_prefixes):
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must not use a development "
            "or generated insecure placeholder in production."
        )

    return value


def _required_absolute_path_env(name):
    raw_value = _required_env(name)
    path_value = Path(raw_value).expanduser()

    if not path_value.is_absolute():
        raise ImproperlyConfigured(
            f"{name} must be an absolute filesystem path."
        )

    return path_value.resolve()


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


def _production_redis_url():
    value = _required_env("REDIS_URL")

    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError as exc:
        raise ImproperlyConfigured(
            "REDIS_URL must be a valid redis:// or rediss:// URL."
        ) from exc

    if (
        parsed.scheme not in {"redis", "rediss"}
        or not parsed.hostname
        or any(character.isspace() for character in value)
    ):
        raise ImproperlyConfigured(
            "REDIS_URL must be a valid redis:// or rediss:// URL."
        )

    return value


def _production_site_base_url():
    _required_env("SITE_BASE_URL")
    value = os.getenv("SITE_BASE_URL", "")
    try:
        return validate_site_base_url(value, require_https=True)
    except ValueError:
        raise ImproperlyConfigured(
            "SITE_BASE_URL must be a valid absolute HTTPS URL."
        ) from None


if IS_PRODUCTION:
    SECRET_KEY = _production_secret_key()
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
    "assistant.apps.AssistantConfig",
    "adminx.apps.AdminxConfig",
    "core.apps.CoreConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.session_security.SessionSecurityMiddleware",
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


# Development remains intentionally lightweight. Production is fail-closed:
# it must never fall back to SQLite or process-local cache.
if IS_PRODUCTION:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _required_env("POSTGRES_DB"),
            "USER": _required_env("POSTGRES_USER"),
            "PASSWORD": _required_env(
                "POSTGRES_PASSWORD"
            ),
            "HOST": _required_env("POSTGRES_HOST"),
            "PORT": str(
                _positive_env_int(
                    "POSTGRES_PORT",
                    default=5432,
                )
            ),
            "CONN_MAX_AGE": (
                _nonnegative_env_int(
                    "POSTGRES_CONN_MAX_AGE",
                    default=60,
                )
            ),
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {
                "connect_timeout":
                    _positive_env_int(
                        "POSTGRES_CONNECT_TIMEOUT",
                        default=5,
                    ),
            },
        }
    }

    CACHES = {
        "default": {
            "BACKEND": (
                "django.core.cache.backends.redis."
                "RedisCache"
            ),
            "LOCATION": _production_redis_url(),
            "TIMEOUT": 300,
            "KEY_PREFIX": "dertderman",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": (
                "django.db.backends.sqlite3"
            ),
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

    CACHES = {
        "default": {
            "BACKEND": (
                "django.core.cache.backends.locmem."
                "LocMemCache"
            ),
            "LOCATION": "dertderman-development",
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {
            "min_length": 12,
        },
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Production stores new passwords with Argon2id.
# Existing PBKDF2 hashes remain verifiable and Django can
# transparently upgrade them after a successful authentication.
if IS_PRODUCTION:
    PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.Argon2PasswordHasher",
        "django.contrib.auth.hashers.PBKDF2PasswordHasher",
        "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
        "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
        "django.contrib.auth.hashers.ScryptPasswordHasher",
    ]
else:
    # Keep local development and the large regression suite
    # lightweight while retaining Django's secure PBKDF2 default.
    PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.PBKDF2PasswordHasher",
        "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
        "django.contrib.auth.hashers.Argon2PasswordHasher",
        "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
        "django.contrib.auth.hashers.ScryptPasswordHasher",
    ]


LANGUAGE_CODE = "tr-tr"

TIME_ZONE = "Europe/Istanbul"

USE_I18N = True

USE_TZ = True


STATIC_URL = "/static/"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

MEDIA_URL = "/media/"

if IS_PRODUCTION:
    STATIC_ROOT = _required_absolute_path_env(
        "DJANGO_STATIC_ROOT"
    )
    MEDIA_ROOT = _required_absolute_path_env(
        "DJANGO_MEDIA_ROOT"
    )

    if (
        STATIC_ROOT == MEDIA_ROOT
        or STATIC_ROOT in MEDIA_ROOT.parents
        or MEDIA_ROOT in STATIC_ROOT.parents
    ):
        raise ImproperlyConfigured(
            "DJANGO_STATIC_ROOT and DJANGO_MEDIA_ROOT "
            "must not overlap."
        )

    STORAGES = {
        "default": {
            "BACKEND": (
                "django.core.files.storage."
                "FileSystemStorage"
            ),
        },
        "staticfiles": {
            "BACKEND": (
                "django.contrib.staticfiles.storage."
                "ManifestStaticFilesStorage"
            ),
        },
    }
else:
    STATIC_ROOT = (
        BASE_DIR / "staticfiles"
    )
    MEDIA_ROOT = (
        BASE_DIR / "media"
    )

    STORAGES = {
        "default": {
            "BACKEND": (
                "django.core.files.storage."
                "FileSystemStorage"
            ),
        },
        "staticfiles": {
            "BACKEND": (
                "django.contrib.staticfiles.storage."
                "StaticFilesStorage"
            ),
        },
    }


# Uploaded files larger than 1 MiB are streamed to a
# temporary file rather than being retained entirely in RAM.
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024

# Limit non-file POST body memory consumption.
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# Current application flows accept a single image at a time.
# Keep a small safety margin for future multipart forms.
DATA_UPLOAD_MAX_NUMBER_FILES = 4


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "core:home"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Do not trust client-controlled forwarded host/port headers.
# Proxy protocol trust is handled separately and must only be
# enabled when the origin can be reached exclusively through
# a trusted reverse proxy.
USE_X_FORWARDED_HOST = False
USE_X_FORWARDED_PORT = False

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

SESSION_COOKIE_PATH = "/"
CSRF_COOKIE_PATH = "/"
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_DOMAIN = None

# Server-side authentication session limits.
#
# Cookie expiry alone is not a strict absolute login lifetime:
# application code may modify/save sessions during normal use.
# The middleware keeps an independent fixed login timestamp.
AUTH_SESSION_SECURITY_ENABLED = _strict_env_bool(
    "DJANGO_AUTH_SESSION_SECURITY_ENABLED",
    default=IS_PRODUCTION,
)

AUTH_SESSION_ACTIVITY_TOUCH_SECONDS = _positive_env_int(
    "DJANGO_SESSION_ACTIVITY_TOUCH_SECONDS",
    default=60,
)

AUTH_SESSION_SECURITY_POLICIES = {
    "USER": {
        "idle_seconds": _positive_env_int(
            "DJANGO_USER_SESSION_IDLE_SECONDS",
            default=8 * 60 * 60,
        ),
        "absolute_seconds": _positive_env_int(
            "DJANGO_USER_SESSION_ABSOLUTE_SECONDS",
            default=8 * 60 * 60,
        ),
    },
    "COMPANY": {
        "idle_seconds": _positive_env_int(
            "DJANGO_COMPANY_SESSION_IDLE_SECONDS",
            default=2 * 60 * 60,
        ),
        "absolute_seconds": _positive_env_int(
            "DJANGO_COMPANY_SESSION_ABSOLUTE_SECONDS",
            default=8 * 60 * 60,
        ),
    },
    "ADMIN": {
        "idle_seconds": _positive_env_int(
            "DJANGO_ADMIN_SESSION_IDLE_SECONDS",
            default=30 * 60,
        ),
        "absolute_seconds": _positive_env_int(
            "DJANGO_ADMIN_SESSION_ABSOLUTE_SECONDS",
            default=4 * 60 * 60,
        ),
    },
}

AUTH_SESSION_MAX_ACTIVE_SESSIONS = {
    "USER": _positive_env_int(
        "DJANGO_USER_MAX_ACTIVE_SESSIONS",
        default=5,
    ),
    "COMPANY": _positive_env_int(
        "DJANGO_COMPANY_MAX_ACTIVE_SESSIONS",
        default=3,
    ),
    "ADMIN": _positive_env_int(
        "DJANGO_ADMIN_MAX_ACTIVE_SESSIONS",
        default=2,
    ),
}


for _role, _policy in (
    AUTH_SESSION_SECURITY_POLICIES.items()
):
    if (
        _policy["idle_seconds"]
        > _policy["absolute_seconds"]
    ):
        raise ImproperlyConfigured(
            f"{_role} session idle timeout "
            "cannot exceed its absolute timeout."
        )

CSRF_FAILURE_VIEW = "core.error_views.csrf_failure"

if IS_PRODUCTION:
    # __Host- cookies must be Secure, host-only and Path=/.
    # This prevents sibling/subdomains from planting or
    # overwriting the application's authentication cookies.
    SESSION_COOKIE_NAME = "__Host-dd_session"
    CSRF_COOKIE_NAME = "__Host-dd_csrf"

    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # Production session cookie lifetime: 8 hours by default.
    # Strict role-specific idle/absolute login lifetimes are
    # enforced independently by SessionSecurityMiddleware.
    # Closing the browser also expires the browser cookie.
    SESSION_COOKIE_AGE = _positive_env_int(
        "DJANGO_SESSION_COOKIE_AGE",
        default=8 * 60 * 60,
    )
    SESSION_EXPIRE_AT_BROWSER_CLOSE = True

    # Do not force Django to save the whole session on every
    # request. SessionSecurityMiddleware touches activity at a
    # bounded interval instead.
    SESSION_SAVE_EVERY_REQUEST = False

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
    SESSION_COOKIE_NAME = "sessionid"
    CSRF_COOKIE_NAME = "csrftoken"

    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

    SESSION_COOKIE_AGE = 14 * 24 * 60 * 60
    SESSION_EXPIRE_AT_BROWSER_CLOSE = False
    SESSION_SAVE_EVERY_REQUEST = False

    SECURE_SSL_REDIRECT = False
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False


# Mail transport configuration. Business rules and token generation do not
# belong here; these values only configure the provider-neutral email service.
EMAIL_PROVIDER = (os.getenv("EMAIL_PROVIDER", "resend") or "resend").strip().lower()
EMAIL_SENDING_ENABLED = _strict_env_bool("EMAIL_SENDING_ENABLED", default=False)
TRANSACTIONAL_EMAILS_ENABLED = _env_bool(
    "TRANSACTIONAL_EMAILS_ENABLED",
    default=True,
)
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
RESEND_WEBHOOK_SECRET = os.getenv("RESEND_WEBHOOK_SECRET", "").strip()
RESEND_WEBHOOK_MAX_BODY_BYTES = _positive_env_int(
    "RESEND_WEBHOOK_MAX_BODY_BYTES",
    default=131072,
)
RESEND_TIMEOUT_SECONDS = _positive_env_int(
    "RESEND_TIMEOUT_SECONDS",
    default=30,
)

if IS_PRODUCTION and EMAIL_SENDING_ENABLED:
    if EMAIL_PROVIDER != "resend":
        raise ImproperlyConfigured(
            "EMAIL_PROVIDER must be 'resend' when email sending is enabled "
            "in production."
        )
    if not RESEND_API_KEY:
        raise ImproperlyConfigured(
            "RESEND_API_KEY is required when email sending is enabled in "
            "production."
        )
    if not RESEND_WEBHOOK_SECRET:
        raise ImproperlyConfigured(
            "RESEND_WEBHOOK_SECRET is required when email sending is enabled "
            "in production."
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
PASSWORD_RESET_TIMEOUT = _positive_env_int(
    "PASSWORD_RESET_TIMEOUT",
    default=300,
)


# Verification links are valid for 30 minutes by default.
EMAIL_VERIFICATION_TIMEOUT = _positive_env_int(
    "EMAIL_VERIFICATION_TIMEOUT",
    default=1800,
)
EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS = _positive_env_int(
    "EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS",
    default=60,
)

# Authenticated email-change links are valid for 10 minutes by default.
EMAIL_CHANGE_TIMEOUT = _positive_env_int(
    "EMAIL_CHANGE_TIMEOUT",
    default=600,
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
