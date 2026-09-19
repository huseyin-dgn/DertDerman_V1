from dataclasses import dataclass
from hashlib import sha256
import hmac
import logging

from django.conf import settings
from django.core.cache import cache

from .client_ip import get_client_ip as client_ip


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    count: int
    limit: int
    retry_after: int


@dataclass(frozen=True)
class AuthRateLimitPolicy:
    pair_limit: int
    pair_window_seconds: int
    identity_limit: int
    identity_window_seconds: int
    ip_limit: int
    ip_window_seconds: int


@dataclass(frozen=True)
class AuthRateLimitResult:
    allowed: bool
    retry_after: int


def _enabled() -> bool:
    return bool(getattr(settings, "RATE_LIMIT_ENABLED", True))


def _normalized_identifier(identifier) -> str:
    return str(identifier if identifier is not None else "").strip().casefold()


def _auth_pair_identifier(
    ip_address: str,
    identity: str,
) -> str:
    """
    Authentication rate-limit pair anahtarı için tek canonical
    temsil kullanılır.

    NUL separator, IP ve identity alanlarının birbirine
    karışmasını önler.
    """
    return (
        f"{ip_address}\x00"
        f"{_normalized_identifier(identity)}"
    )


def build_rate_limit_key(*, scope: str, identifier) -> str:
    scope = (scope or "generic").strip().lower()

    # Identifiers such as email addresses, usernames and IPs are
    # low-entropy values. A plain SHA-256 digest could be dictionary
    # matched if the cache contents were ever exposed. Key the digest
    # with Django's production secret instead.
    payload = (
        f"{scope}\0{_normalized_identifier(identifier)}"
    ).encode("utf-8")

    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        payload,
        sha256,
    ).hexdigest()

    return f"dertderman:rl:v2:{scope}:{digest}"


def rate_limit_status(
    *,
    scope: str,
    identifier,
    limit: int,
    window_seconds: int,
) -> RateLimitResult:
    if not _enabled():
        return RateLimitResult(True, 0, limit, 0)

    key = build_rate_limit_key(
        scope=scope,
        identifier=identifier,
    )

    try:
        count = int(cache.get(key, 0) or 0)
    except Exception as exc:
        # Security throttles must not silently disappear when Redis
        # or another shared cache backend becomes unavailable.
        logger.error(
            "Rate-limit backend unavailable: "
            "operation=status scope=%s exception_type=%s",
            scope,
            exc.__class__.__name__,
        )
        return RateLimitResult(
            allowed=False,
            count=limit,
            limit=limit,
            retry_after=int(window_seconds),
        )

    allowed = count < limit

    return RateLimitResult(
        allowed=allowed,
        count=count,
        limit=limit,
        retry_after=(
            0
            if allowed
            else int(window_seconds)
        ),
    )


def consume_rate_limit(
    *,
    scope: str,
    identifier,
    limit: int,
    window_seconds: int,
) -> RateLimitResult:
    if not _enabled():
        return RateLimitResult(True, 0, limit, 0)

    key = build_rate_limit_key(
        scope=scope,
        identifier=identifier,
    )

    try:
        if cache.add(
            key,
            1,
            timeout=window_seconds,
        ):
            count = 1
        else:
            try:
                count = int(cache.incr(key))
            except ValueError:
                # The key may have expired between add() and incr().
                # Recreate it with the original TTL rather than
                # silently treating the attempt as uncounted.
                cache.set(
                    key,
                    1,
                    timeout=window_seconds,
                )
                count = 1

    except Exception as exc:
        logger.error(
            "Rate-limit backend unavailable: "
            "operation=consume scope=%s exception_type=%s",
            scope,
            exc.__class__.__name__,
        )

        return RateLimitResult(
            allowed=False,
            count=limit,
            limit=limit,
            retry_after=int(window_seconds),
        )

    allowed = count <= limit

    return RateLimitResult(
        allowed=allowed,
        count=count,
        limit=limit,
        retry_after=(
            0
            if allowed
            else int(window_seconds)
        ),
    )


def clear_rate_limit(
    *,
    scope: str,
    identifier,
) -> None:
    if not _enabled():
        return

    try:
        cache.delete(
            build_rate_limit_key(
                scope=scope,
                identifier=identifier,
            )
        )
    except Exception as exc:
        # Do not turn an already-authenticated successful login into
        # an application error solely because cleanup failed.
        # The stale limiter remains conservative until its TTL expires.
        logger.error(
            "Rate-limit backend unavailable: "
            "operation=clear scope=%s exception_type=%s",
            scope,
            exc.__class__.__name__,
        )


def auth_rate_limit_status(
    *,
    scope: str,
    ip_address: str,
    identity: str,
    policy: AuthRateLimitPolicy,
) -> AuthRateLimitResult:
    """
    Authentication başlamadan önce mevcut failure sayaçlarını
    kontrol eder.

    Bu fonksiyon sayaç artırmaz. Böylece başarılı girişler
    brute-force kotasını tüketmez.
    """
    normalized_identity = _normalized_identifier(
        identity
    )

    decisions = (
        rate_limit_status(
            scope=f"{scope}-pair",
            identifier=_auth_pair_identifier(
                ip_address,
                normalized_identity,
            ),
            limit=policy.pair_limit,
            window_seconds=(
                policy.pair_window_seconds
            ),
        ),
        rate_limit_status(
            scope=f"{scope}-identity",
            identifier=normalized_identity,
            limit=policy.identity_limit,
            window_seconds=(
                policy.identity_window_seconds
            ),
        ),
        rate_limit_status(
            scope=f"{scope}-ip",
            identifier=ip_address,
            limit=policy.ip_limit,
            window_seconds=(
                policy.ip_window_seconds
            ),
        ),
    )

    denied_retry_after = [
        decision.retry_after
        for decision in decisions
        if not decision.allowed
    ]

    return AuthRateLimitResult(
        allowed=not denied_retry_after,
        retry_after=max(
            denied_retry_after,
            default=0,
        ),
    )


def consume_auth_failure(
    *,
    scope: str,
    ip_address: str,
    identity: str,
    policy: AuthRateLimitPolicy,
) -> AuthRateLimitResult:
    """
    Yalnızca başarısız authentication sonrasında çağrılır.
    """
    normalized_identity = _normalized_identifier(
        identity
    )

    decisions = (
        consume_rate_limit(
            scope=f"{scope}-pair",
            identifier=_auth_pair_identifier(
                ip_address,
                normalized_identity,
            ),
            limit=policy.pair_limit,
            window_seconds=(
                policy.pair_window_seconds
            ),
        ),
        consume_rate_limit(
            scope=f"{scope}-identity",
            identifier=normalized_identity,
            limit=policy.identity_limit,
            window_seconds=(
                policy.identity_window_seconds
            ),
        ),
        consume_rate_limit(
            scope=f"{scope}-ip",
            identifier=ip_address,
            limit=policy.ip_limit,
            window_seconds=(
                policy.ip_window_seconds
            ),
        ),
    )

    denied_retry_after = [
        decision.retry_after
        for decision in decisions
        if not decision.allowed
    ]

    return AuthRateLimitResult(
        allowed=not denied_retry_after,
        retry_after=max(
            denied_retry_after,
            default=0,
        ),
    )


def clear_auth_identity(
    *,
    scope: str,
    ip_address: str,
    identity: str,
) -> None:
    normalized_identity = _normalized_identifier(
        identity
    )

    # Successful authentication clears account-targeted buckets,
    # but deliberately does NOT clear the global IP bucket. This
    # prevents one valid credential from resetting account-spraying
    # protection for an attacking source address.
    clear_rate_limit(
        scope=f"{scope}-pair",
        identifier=_auth_pair_identifier(
                ip_address,
                normalized_identity,
            ),
    )

    clear_rate_limit(
        scope=f"{scope}-identity",
        identifier=normalized_identity,
    )
