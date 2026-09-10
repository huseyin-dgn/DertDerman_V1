from urllib.parse import urlsplit

from django.urls import Resolver404, resolve
from django.utils.http import url_has_allowed_host_and_scheme

from .models import User


ROLE_NAMESPACES = {
    User.UserType.USER: {"accounts", "blog", "companies_public", "complaints", "core", "dashboard", "notifications"},
    User.UserType.COMPANY: {"companies"},
    User.UserType.ADMIN: {"adminx"},
}

REJECTED_AUTH_ROUTES = {
    ("accounts", "entry"),
    ("accounts", "login"),
    ("accounts", "logout"),
    ("accounts", "register"),
    ("adminx", "login"),
}


def safe_role_next(request, user_type):
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return ""

    try:
        match = resolve(urlsplit(candidate).path)
    except (Resolver404, ValueError):
        return ""

    if match.namespace not in ROLE_NAMESPACES.get(user_type, set()):
        return ""
    if (match.namespace, match.url_name) in REJECTED_AUTH_ROUTES:
        return ""
    return candidate
