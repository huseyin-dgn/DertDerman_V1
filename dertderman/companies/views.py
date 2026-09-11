from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.db.models import Count, Q
from django.views.decorators.http import require_POST, require_safe
from core.pagination import paginate
from core.decorators import role_required
from accounts.models import User

from complaints.selectors import public_complaints
from complaints.forms import CompanyReportForm
from complaints.models import CompanyReport
from complaints.reporting_policy import check_general_reporting_allowed

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
        "company_report_form": CompanyReportForm(),
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




@role_required(User.UserType.USER)
@require_POST
def public_company_report(request, slug):
    company = get_object_or_404(
        public_companies(),
        slug=slug,
    )

    policy = check_general_reporting_allowed(
        user=request.user,
        request=request,
    )
    if not policy.allowed:
        messages.error(request, policy.message)
        return redirect(
            "companies_public:company_detail",
            slug=company.slug,
        )

    if CompanyReport.objects.filter(
        reporter=request.user,
        company=company,
    ).exists():
        messages.info(
            request,
            "Bu şirketi daha önce raporladınız.",
        )
        return redirect(
            "companies_public:company_detail",
            slug=company.slug,
        )

    form = CompanyReportForm(request.POST)

    if not form.is_valid():
        messages.error(
            request,
            "Şirket raporu gönderilemedi. Lütfen geçerli bir neden seçin.",
        )
        return redirect(
            "companies_public:company_detail",
            slug=company.slug,
        )

    report = form.save(commit=False)
    report.reporter = request.user
    report.company = company
    report.status = CompanyReport.Status.PENDING

    try:
        with transaction.atomic():
            report.save()
            from notifications.services import notify_admins_company_report
            notify_admins_company_report(report)

    except (ValidationError, IntegrityError):
        messages.info(
            request,
            "Bu şirketi daha önce raporladınız.",
        )
        return redirect(
            "companies_public:company_detail",
            slug=company.slug,
        )

    messages.success(
        request,
        "Şirket raporunuz alındı ve yönetim incelemesine gönderildi.",
    )
    return redirect(
        "companies_public:company_detail",
        slug=company.slug,
    )
