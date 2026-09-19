import ipaddress

from django.conf import settings


def _valid_ip(raw_value):
    value = (raw_value or "").strip()
    if not value:
        return None

    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def get_client_ip(request):
    if request is None:
        return None

    if getattr(settings, "TRUST_CLOUDFLARE_CONNECTING_IP", False):
        cloudflare_ip = _valid_ip(
            request.META.get("HTTP_CF_CONNECTING_IP")
        )
        if cloudflare_ip is not None:
            return cloudflare_ip

    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if "," not in forwarded_for:
            forwarded_ip = _valid_ip(forwarded_for)
            if forwarded_ip is not None:
                return forwarded_ip

    return _valid_ip(request.META.get("REMOTE_ADDR")) or "unknown"
