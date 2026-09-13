from dataclasses import dataclass
from hashlib import sha256
import ipaddress

from django.conf import settings
from django.core.cache import cache


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    count: int
    limit: int
    retry_after: int


def _enabled() -> bool:
    return bool(getattr(settings, "RATE_LIMIT_ENABLED", True))


def _normalized_identifier(identifier) -> str:
    return str(identifier if identifier is not None else "").strip().casefold()


def build_rate_limit_key(*, scope: str, identifier) -> str:
    scope = (scope or "generic").strip().lower()
    digest = sha256(_normalized_identifier(identifier).encode("utf-8")).hexdigest()
    return f"dertderman:rl:v1:{scope}:{digest}"


def client_ip(request) -> str:
    candidates = []
    if getattr(settings, "TRUST_CLOUDFLARE_CONNECTING_IP", False):
        candidates.append(request.META.get("HTTP_CF_CONNECTING_IP", ""))
    candidates.append(request.META.get("REMOTE_ADDR", ""))

    for raw in candidates:
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            return str(ipaddress.ip_address(raw))
        except ValueError:
            continue
    return "unknown"


def rate_limit_status(*, scope: str, identifier, limit: int, window_seconds: int) -> RateLimitResult:
    if not _enabled():
        return RateLimitResult(True, 0, limit, 0)

    key = build_rate_limit_key(scope=scope, identifier=identifier)
    try:
        count = int(cache.get(key, 0) or 0)
    except (TypeError, ValueError):
        count = 0

    allowed = count < limit
    return RateLimitResult(
        allowed=allowed,
        count=count,
        limit=limit,
        retry_after=0 if allowed else int(window_seconds),
    )


def consume_rate_limit(*, scope: str, identifier, limit: int, window_seconds: int) -> RateLimitResult:
    if not _enabled():
        return RateLimitResult(True, 0, limit, 0)

    key = build_rate_limit_key(scope=scope, identifier=identifier)
    if cache.add(key, 1, timeout=window_seconds):
        count = 1
    else:
        try:
            count = int(cache.incr(key))
        except ValueError:
            cache.set(key, 1, timeout=window_seconds)
            count = 1

    allowed = count <= limit
    return RateLimitResult(
        allowed=allowed,
        count=count,
        limit=limit,
        retry_after=0 if allowed else int(window_seconds),
    )


def clear_rate_limit(*, scope: str, identifier) -> None:
    if not _enabled():
        return
    cache.delete(build_rate_limit_key(scope=scope, identifier=identifier))
