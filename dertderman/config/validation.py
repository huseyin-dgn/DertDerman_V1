from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


def validate_site_base_url(value, *, require_https):
    """Return a normalized absolute site origin or raise a sanitized error."""
    if (
        not isinstance(value, str)
        or not value
        or any(character.isspace() for character in value)
    ):
        raise ValueError("SITE_BASE_URL is invalid.")

    allowed_schemes = ["https"] if require_https else ["http", "https"]
    try:
        parsed = urlsplit(value)
        parsed.port
        URLValidator(schemes=allowed_schemes)(value)
    except (TypeError, ValueError, ValidationError):
        raise ValueError("SITE_BASE_URL is invalid.") from None

    if (
        parsed.scheme not in allowed_schemes
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("SITE_BASE_URL is invalid.")

    return value.rstrip("/")
