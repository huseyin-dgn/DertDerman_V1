from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import resolve_url
from django.views.decorators.cache import never_cache


def role_required(*allowed_roles):
    allowed_roles = set(allowed_roles)

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                login_url = resolve_url(settings.LOGIN_URL)
                return redirect_to_login(request.get_full_path(), login_url)

            if getattr(request.user, "user_type", None) not in allowed_roles:
                raise PermissionDenied

            return view_func(request, *args, **kwargs)

        return never_cache(wrapped)

    return decorator
