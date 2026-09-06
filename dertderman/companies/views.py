from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from accounts.models import User
from core.decorators import role_required
from complaints.selectors import public_complaints

from .models import Company
from .services import active_company_memberships_for, get_accessible_company_membership


@role_required(User.UserType.COMPANY)
def company_panel(request):
    memberships = active_company_memberships_for(request.user)
    if not memberships.exists():
        raise PermissionDenied

    return render(
        request,
        "companies/company_dashboard.html",
        {"memberships": memberships},
    )


@role_required(User.UserType.COMPANY)
def company_panel_detail(request, slug):
    membership = get_accessible_company_membership(request.user, slug)
    return render(
        request,
        "companies/company_panel_detail.html",
        {"company": membership.company, "membership": membership},
    )


def public_company_list(request):
    companies = (
        Company.objects.filter(is_active=True)
        .select_related("category")
        .order_by("name")
    )
    return render(
        request,
        "companies/company_list.html",
        {"companies": companies},
    )


def public_company_detail(request, slug):
    company = get_object_or_404(
        Company.objects.filter(is_active=True).select_related("category"),
        slug=slug,
    )
    return render(
        request,
        "companies/company_detail.html",
        {"company": company, "recent_public_complaints": public_complaints().filter(company=company).defer("description")[:5]},
    )
