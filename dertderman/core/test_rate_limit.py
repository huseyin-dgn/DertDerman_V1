from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings

from .rate_limit import (
    build_rate_limit_key,
    clear_rate_limit,
    client_ip,
    consume_rate_limit,
    rate_limit_status,
)


@override_settings(RATE_LIMIT_ENABLED=True)
class RateLimitPrimitiveTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def test_key_is_stable_and_hides_raw_identifier(self):
        first = build_rate_limit_key(scope="login", identifier="User@Example.com")
        second = build_rate_limit_key(scope="login", identifier=" user@example.com ")
        self.assertEqual(first, second)
        self.assertNotIn("user@example.com", first)

    def test_consume_blocks_after_limit(self):
        self.assertTrue(consume_rate_limit(scope="t", identifier="x", limit=2, window_seconds=60).allowed)
        self.assertTrue(consume_rate_limit(scope="t", identifier="x", limit=2, window_seconds=60).allowed)
        self.assertFalse(consume_rate_limit(scope="t", identifier="x", limit=2, window_seconds=60).allowed)
        self.assertFalse(rate_limit_status(scope="t", identifier="x", limit=2, window_seconds=60).allowed)

    def test_clear_resets_bucket(self):
        consume_rate_limit(scope="t", identifier="x", limit=1, window_seconds=60)
        clear_rate_limit(scope="t", identifier="x")
        self.assertTrue(rate_limit_status(scope="t", identifier="x", limit=1, window_seconds=60).allowed)

    @override_settings(
        TRUST_X_FORWARDED_FOR=False,
        TRUST_CLOUDFLARE_CONNECTING_IP=False,
    )
    def test_forwarded_header_is_not_trusted_by_default(self):
        request = self.factory.get(
            "/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="203.0.113.5",
        )
        self.assertEqual(client_ip(request), "127.0.0.1")

    @override_settings(
        TRUST_X_FORWARDED_FOR=False,
        TRUST_CLOUDFLARE_CONNECTING_IP=False,
    )
    def test_remote_addr_is_used_by_default(self):
        request = self.factory.get("/", REMOTE_ADDR="2001:db8::1")
        self.assertEqual(client_ip(request), "2001:db8::1")

    @override_settings(
        TRUST_X_FORWARDED_FOR=True,
        TRUST_CLOUDFLARE_CONNECTING_IP=False,
    )
    def test_single_valid_forwarded_ip_can_be_trusted(self):
        request = self.factory.get(
            "/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="203.0.113.5",
        )
        self.assertEqual(client_ip(request), "203.0.113.5")

    @override_settings(
        TRUST_X_FORWARDED_FOR=True,
        TRUST_CLOUDFLARE_CONNECTING_IP=False,
    )
    def test_forwarded_chain_is_rejected(self):
        request = self.factory.get(
            "/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="203.0.113.5, 198.51.100.8",
        )
        self.assertEqual(client_ip(request), "127.0.0.1")

    @override_settings(
        TRUST_X_FORWARDED_FOR=True,
        TRUST_CLOUDFLARE_CONNECTING_IP=False,
    )
    def test_invalid_forwarded_ip_is_rejected(self):
        request = self.factory.get(
            "/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="not-an-ip",
        )
        self.assertEqual(client_ip(request), "127.0.0.1")

    @override_settings(TRUST_CLOUDFLARE_CONNECTING_IP=False)
    def test_cf_header_is_not_trusted_by_default(self):
        request = self.factory.get("/", REMOTE_ADDR="127.0.0.1", HTTP_CF_CONNECTING_IP="203.0.113.5")
        self.assertEqual(client_ip(request), "127.0.0.1")

    @override_settings(TRUST_CLOUDFLARE_CONNECTING_IP=True)
    def test_cf_header_can_be_explicitly_trusted(self):
        request = self.factory.get("/", REMOTE_ADDR="127.0.0.1", HTTP_CF_CONNECTING_IP="203.0.113.5")
        self.assertEqual(client_ip(request), "203.0.113.5")
