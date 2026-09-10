from django.shortcuts import get_object_or_404, render
from django.db.models import Count, Q
from django.views.decorators.http import require_safe
from core.pagination import paginate

from complaints.selectors import public_complaints

from .models import Company, CompanyResponse
from .selectors import public_companies, public_company_performance
from .badges import primary_company_badge, resolve_company_badges_from_performance
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
    complaints = public_complaints().filter(company=company)
    active_filter = request.GET.get("status", "all")
    if active_filter == "answered":
        complaints = complaints.filter(has_response=True)
    elif active_filter == "resolved":
        complaints = complaints.filter(status="RESOLVED")
    elif active_filter != "all":
        active_filter = "all"

    page_obj = paginate(request, complaints, "company_public_complaints")
    recent_responses = (
        CompanyResponse.objects.filter(
            company=company,
            complaint__company=company,
            complaint__status__in=("PUBLISHED", "RESOLVED"),
            complaint__withdrawn_at__isnull=True,
            is_active=True,
        )
        .select_related("complaint")
        .order_by("-created_at", "-pk")[:4]
    )
    performance = public_company_performance(company)
    average_response = _format_response_time(performance["average_response_seconds"])
    company_badges = resolve_company_badges_from_performance(company, performance)
    return render(request, "companies/company_detail.html", {
        "company": company,
        "page_obj": page_obj,
        "active_filter": active_filter,
        "filter_options": (
            ("all", "Tümü"),
            ("answered", "Şirket Cevapladı"),
            ("resolved", "Çözüldü"),
        ),
        "performance": performance,
        "average_response": average_response,
        "recent_responses": recent_responses,
        "company_badges": company_badges,
        "primary_company_badge": primary_company_badge(company_badges),
    })


def _format_response_time(seconds):
    if seconds is None:
        return None
    total_minutes = max(0, round(seconds / 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours} sa {minutes} dk"
    if hours:
        return f"{hours} sa"
    return f"{minutes} dk"
