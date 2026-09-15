from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import resolve_url
from django.views.decorators.cache import never_cache


SAFE_ACCOUNT_METHODS = frozenset(("GET", "HEAD", "OPTIONS"))


def no_referrer(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        response = view_func(request, *args, **kwargs)
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    return wrapped


def role_required(*allowed_roles, login_url=None):
    allowed_roles = set(allowed_roles)

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                destination = resolve_url(login_url or settings.LOGIN_URL)
                return redirect_to_login(request.get_full_path(), destination)

            if getattr(request.user, "user_type", None) not in allowed_roles:
                raise PermissionDenied

            if (
                not getattr(request.user, "is_active", False)
                or getattr(request.user, "is_permanently_closed", False)
            ):
                raise PermissionDenied

            if (
                request.user.user_type == "USER"
                and request.method not in SAFE_ACCOUNT_METHODS
                and not getattr(
                    request.user,
                    "can_perform_user_mutations",
                    False,
                )
            ):
                raise PermissionDenied

            return view_func(request, *args, **kwargs)

        return never_cache(wrapped)

    return decorator
