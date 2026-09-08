from django.shortcuts import get_object_or_404, render

from complaints.selectors import public_complaints

from .models import Company
from .panel_views import dashboard as company_panel, legacy_company_dashboard as company_panel_detail


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
