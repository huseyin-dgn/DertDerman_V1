from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

from core.session_security import (
    has_recent_reauthentication,
)


def recent_admin_reauthentication_required(
    request,
    *,
    next_url,
):
    """
    Return None when the current session recently completed
    password authentication.

    Otherwise redirect to the admin step-up authentication page.

    The original destructive POST is deliberately NOT replayed.
    After verification the admin returns to a safe GET page and
    must explicitly submit the action again.
    """
    # Development/test ortamlarinda session hardening
    # kapaliysa step-up zorunlulugu da uygulanmaz.
    # Production'da AUTH_SESSION_SECURITY_ENABLED
    # varsayilan olarak aciktir.
    if not getattr(
        settings,
        "AUTH_SESSION_SECURITY_ENABLED",
        False,
    ):
        return None

    if has_recent_reauthentication(
        request.session
    ):
        return None

    query = urlencode(
        {
            "next": next_url,
        }
    )

    return redirect(
        f"{reverse('adminx:reauth')}?{query}"
    )
