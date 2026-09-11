from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, OuterRef, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST, require_safe
from complaints.models import UserReport, UserViolation
from accounts.models import User
from companies.models import Company, CompanyMembership
from core.pagination import paginate
from .filters import ApplicationFilters, CompanyFilters, UserFilters, list_context
from companies.services import decide_company_application
from .decorators import admin_required
from core.presentation import HERO_BRAND_MESSAGES
from .forms import CompanyApprovalActionForm, CompanyContentForm
from .services import archive_company


@admin_required
@require_safe
def company_list(request):
    companies = Company.objects.select_related("category").annotate(complaint_count=Count("complaints"))
    context = list_context(request, companies, CompanyFilters, search_fields=("name", "email"),
        fields={"status": "approval_status", "category": "category", "verified": "is_verified", "active": "is_active"})
    return render(request, "adminx/company_list.html", context)


@admin_required
@require_http_methods(["GET", "HEAD", "POST"])
def company_edit(request, pk):
    company = get_object_or_404(Company, pk=pk)
    form = CompanyContentForm(request.POST if request.method == "POST" else None, instance=company)
    if request.method == "POST" and form.is_valid():
        company = form.save(commit=False)
        company.save(update_fields=[*CompanyContentForm.Meta.fields, "updated_at"])
        messages.success(request, "Şirket bilgileri güncellendi.")
        return redirect("adminx:company_edit", pk=company.pk)
    return render(request, "adminx/company_form.html", {"form": form, "company": company})


@admin_required
@require_safe
def company_application_list(request):
    applicant = CompanyMembership.objects.filter(company_id=OuterRef("pk")).order_by("created_at", "pk")
    applications = Company.objects.select_related("category").annotate(
        applicant_name=Subquery(applicant.values("user__username")[:1]))
    context = list_context(request, applications, ApplicationFilters, search_fields=("name", "email", "applicant_name"), fields={"status": "approval_status"})
    context["applications"] = context["page_obj"]
    return render(request, "adminx/company_application_list.html", context)


@admin_required
@require_http_methods(["GET", "HEAD", "POST"])
def company_application_detail(request, pk):
    company = get_object_or_404(
        Company.objects.select_related("category"),
        pk=pk,
    )
    form = CompanyApprovalActionForm(request.POST if request.method == "POST" else None)
    decision_error = None
    if request.method == "POST" and form.is_valid():
        status_by_action = {
            CompanyApprovalActionForm.Action.APPROVE: Company.ApprovalStatus.APPROVED,
            CompanyApprovalActionForm.Action.REJECT: Company.ApprovalStatus.REJECTED,
        }
        try:
            company, changed = decide_company_application(
                company.pk,
                status_by_action[form.cleaned_data["action"]],
            )
        except ValidationError as error:
            decision_error = error.messages[0]
        else:
            if changed:
                messages.success(
                    request,
                    "Şirket başvurusu onaylandı."
                    if company.approval_status == Company.ApprovalStatus.APPROVED
                    else "Şirket başvurusu reddedildi.",
                )
                return redirect("adminx:company_application_detail", pk=company.pk)
            decision_error = "Bu şirket başvurusu daha önce sonuçlandırılmış."
    return render(
        request,
        "adminx/company_application_detail.html",
        {"company": company, "form": form, "decision_error": decision_error,
         "member_page": paginate(request, company.memberships.select_related("user").order_by("-created_at", "-pk"), "admin", page_param="member_page")},
        status=409 if decision_error else 200,
    )


@admin_required
@require_safe
def user_list(request):
    users = _users()
    context = list_context(request, users, UserFilters,
        search_fields=("username", "first_name", "last_name", "email"),
        fields={"role": "user_type", "active": "is_active"}, ordering=("-date_joined", "-pk"))
    return render(request, "adminx/user_list.html", context)


def _users():
    return User.objects.only("username", "first_name", "last_name", "email", "date_joined", "user_type", "is_active")


@admin_required
@require_safe
def user_detail(request, pk):
    account = get_object_or_404(
        _users(),
        pk=pk,
    )

    violations = (
        UserViolation.objects
        .filter(user=account)
        .select_related(
            "confirmed_by",
            "complaint",
            "comment",
            "content_report",
            "user_report",
        )
        .order_by(
            "-created_at",
            "-pk",
        )
    )

    violation_count = violations.count()

    user_reports = UserReport.objects.filter(
        reported_user=account,
    )

    total_user_reports = user_reports.count()

    pending_user_reports = user_reports.filter(
        status__in=(
            UserReport.Status.PENDING,
            UserReport.Status.REVIEWING,
        )
    ).count()

    rejected_user_reports = user_reports.filter(
        status=UserReport.Status.REJECTED,
    ).count()

    confirmed_user_reports = user_reports.filter(
        status=UserReport.Status.RESOLVED,
    ).count()

    last_violation = violations.first()

    if violation_count == 0:
        risk_level = "Normal"
        risk_code = "NORMAL"

    elif violation_count == 1:
        risk_level = "Uyarı"
        risk_code = "WARNING"

    elif violation_count == 2:
        risk_level = "Tekrarlanan ihlal"
        risk_code = "REPEATED"

    elif violation_count < 5:
        risk_level = "Yüksek risk"
        risk_code = "HIGH"

    else:
        risk_level = "Askıya almaya uygun"
        risk_code = "SUSPEND_ELIGIBLE"

    suspension_eligible = violation_count >= 5

    return render(
        request,
        "adminx/user_detail.html",
        {
            "account": account,

            "violation_count": violation_count,
            "last_violation": last_violation,
            "recent_violations": violations[:10],

            "total_user_reports": total_user_reports,
            "pending_user_reports": pending_user_reports,
            "confirmed_user_reports": confirmed_user_reports,
            "rejected_user_reports": rejected_user_reports,

            "risk_level": risk_level,
            "risk_code": risk_code,
            "suspension_eligible": suspension_eligible,
        },
    )

@admin_required
@require_safe
def homepage_content(request):
    return render(request, "adminx/homepage_content.html", {"hero_brand_messages": HERO_BRAND_MESSAGES})


@admin_required
@require_POST
def company_archive(request, pk):
    changed = archive_company(pk=pk, actor=request.user)
    if changed:
        messages.success(request, "Şirket arşivlendi. Public görünürlüğü ve bu şirkete erişim kapatıldı.")
    else:
        messages.info(request, "Bu şirket daha önce arşivlenmiş.")
    return redirect("adminx:company_edit", pk=pk)
