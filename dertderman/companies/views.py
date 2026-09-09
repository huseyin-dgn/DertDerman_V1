from django.shortcuts import get_object_or_404, render
from django.db.models import Count, Q
from django.views.decorators.http import require_safe
from core.pagination import paginate

from complaints.selectors import public_complaints

from .models import Company
from .selectors import public_companies
from .panel_views import dashboard as company_panel, legacy_company_dashboard as company_panel_detail


@require_safe
def public_company_list(request):
    search = request.GET.get("s", request.GET.get("q", "")).strip()[:180]
    companies = public_companies().annotate(
        public_complaint_count=Count("complaints", filter=Q(complaints__status="PUBLISHED")))
    if search:
        companies = companies.filter(Q(name__icontains=search) | Q(description__icontains=search) | Q(category__name__icontains=search))
    page = paginate(request, companies, "public_companies")
    return render(
        request,
        "companies/company_list.html",
        {"companies": page, "page_obj": page, "search": search},
    )


@require_safe
def public_company_detail(request, slug):
    company = get_object_or_404(
        public_companies(),
        slug=slug,
    )
    return render(
        request,
        "companies/company_detail.html",
        {"company": company, "recent_public_complaints": public_complaints().filter(company=company).defer("description")[:5]},
    )
