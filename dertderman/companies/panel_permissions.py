from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from .models import CompanyMembership
from .services import active_company_memberships_for


PROFILE_ROLES = {CompanyMembership.Role.OWNER, CompanyMembership.Role.MANAGER}
COMPANY_SESSION_KEY = "company_panel_company_id"


def require_company_membership(user, company_id):
    membership = active_company_memberships_for(user).filter(company_id=company_id).first()
    if membership is None:
        raise PermissionDenied
    return membership


def require_profile_role(membership):
    if membership.role not in PROFILE_ROLES:
        raise PermissionDenied


def company_panel_required(view):
    @wraps(view)
    @never_cache
    def wrapped(request, *args, **kwargs):
        try:
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
            memberships = list(active_company_memberships_for(request.user))
            if not memberships:
                raise PermissionDenied
            selected_id = request.session.get(COMPANY_SESSION_KEY)
            membership = next((m for m in memberships if m.company_id == selected_id), memberships[0])
            # A stale selection never grants access; every request rechecks the database.
            request.company_memberships = memberships
            request.company_membership = membership
            request.company = membership.company
            return view(request, *args, **kwargs)
        except (PermissionDenied, Http404) as error:
            return render(request, "companies/panel/access_denied.html", {
                "not_found": isinstance(error, Http404),
            }, status=404 if isinstance(error, Http404) else 403)
    return wrapped
