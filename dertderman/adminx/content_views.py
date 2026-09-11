from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import (
    require_http_methods,
    require_POST,
    require_safe,
)

from accounts.models import User
from companies.models import Company, CompanyMembership
from companies.services import decide_company_application
from complaints.models import Complaint, UserReport, UserViolation
from core.models import AbuseAttempt
from core.pagination import paginate
from core.presentation import HERO_BRAND_MESSAGES

from .decorators import admin_required
from .filters import (
    ApplicationFilters,
    CompanyFilters,
    UserFilters,
    list_context,
)
from .forms import CompanyApprovalActionForm, CompanyContentForm
from .services import archive_company


@admin_required
@require_safe
def company_list(request):
    companies = (
        Company.objects
        .select_related("category")
        .annotate(
            complaint_count=Count("complaints")
        )
    )

    context = list_context(
        request,
        companies,
        CompanyFilters,
        search_fields=(
            "name",
            "email",
        ),
        fields={
            "status": "approval_status",
            "category": "category",
            "verified": "is_verified",
            "active": "is_active",
        },
    )

    return render(
        request,
        "adminx/company_list.html",
        context,
    )


@admin_required
@require_http_methods(
    [
        "GET",
        "HEAD",
        "POST",
    ]
)
def company_edit(request, pk):
    company = get_object_or_404(
        Company,
        pk=pk,
    )

    form = CompanyContentForm(
        request.POST
        if request.method == "POST"
        else None,
        instance=company,
    )

    if (
        request.method == "POST"
        and form.is_valid()
    ):
        company = form.save(
            commit=False
        )

        company.save(
            update_fields=[
                *CompanyContentForm.Meta.fields,
                "updated_at",
            ]
        )

        messages.success(
            request,
            "Şirket bilgileri güncellendi.",
        )

        return redirect(
            "adminx:company_edit",
            pk=company.pk,
        )

    return render(
        request,
        "adminx/company_form.html",
        {
            "form": form,
            "company": company,
        },
    )


@admin_required
@require_safe
def company_application_list(request):
    applicant = (
        CompanyMembership.objects
        .filter(
            company_id=OuterRef(
                "pk"
            )
        )
        .order_by(
            "created_at",
            "pk",
        )
    )

    applications = (
        Company.objects
        .select_related(
            "category"
        )
        .annotate(
            applicant_name=Subquery(
                applicant.values(
                    "user__username"
                )[:1]
            )
        )
    )

    context = list_context(
        request,
        applications,
        ApplicationFilters,
        search_fields=(
            "name",
            "email",
            "applicant_name",
        ),
        fields={
            "status":
                "approval_status",
        },
    )

    context[
        "applications"
    ] = context["page_obj"]

    return render(
        request,
        "adminx/company_application_list.html",
        context,
    )


@admin_required
@require_http_methods(
    [
        "GET",
        "HEAD",
        "POST",
    ]
)
def company_application_detail(
    request,
    pk,
):
    company = get_object_or_404(
        Company.objects.select_related(
            "category"
        ),
        pk=pk,
    )

    form = CompanyApprovalActionForm(
        request.POST
        if request.method == "POST"
        else None
    )

    decision_error = None

    if (
        request.method == "POST"
        and form.is_valid()
    ):
        status_by_action = {
            CompanyApprovalActionForm.Action.APPROVE:
                Company.ApprovalStatus.APPROVED,

            CompanyApprovalActionForm.Action.REJECT:
                Company.ApprovalStatus.REJECTED,
        }

        try:
            company, changed = (
                decide_company_application(
                    company.pk,
                    status_by_action[
                        form.cleaned_data[
                            "action"
                        ]
                    ],
                )
            )

        except ValidationError as error:
            decision_error = (
                error.messages[0]
            )

        else:
            if changed:
                messages.success(
                    request,
                    (
                        "Şirket başvurusu onaylandı."
                        if (
                            company.approval_status
                            == Company.ApprovalStatus.APPROVED
                        )
                        else
                        "Şirket başvurusu reddedildi."
                    ),
                )

                return redirect(
                    "adminx:company_application_detail",
                    pk=company.pk,
                )

            decision_error = (
                "Bu şirket başvurusu "
                "daha önce sonuçlandırılmış."
            )

    return render(
        request,
        "adminx/company_application_detail.html",
        {
            "company":
                company,

            "form":
                form,

            "decision_error":
                decision_error,

            "member_page":
                paginate(
                    request,
                    (
                        company.memberships
                        .select_related(
                            "user"
                        )
                        .order_by(
                            "-created_at",
                            "-pk",
                        )
                    ),
                    "admin",
                    page_param="member_page",
                ),
        },
        status=(
            409
            if decision_error
            else 200
        ),
    )


@admin_required
@require_safe
def user_list(request):
    users = _users()

    context = list_context(
        request,
        users,
        UserFilters,
        search_fields=(
            "username",
            "first_name",
            "last_name",
            "email",
        ),
        fields={
            "role":
                "user_type",

            "active":
                "is_active",
        },
        ordering=(
            "-date_joined",
            "-pk",
        ),
    )

    return render(
        request,
        "adminx/user_list.html",
        context,
    )


def _users():
    return User.objects.only(
        "username",
        "first_name",
        "last_name",
        "email",
        "date_joined",
        "user_type",
        "is_active",
    )


@admin_required
@require_safe
def user_detail(
    request,
    pk,
):
    account = get_object_or_404(
        _users(),
        pk=pk,
    )

    violations = (
        UserViolation.objects
        .filter(
            user=account
        )
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

    violation_count = (
        violations.count()
    )

    user_reports = (
        UserReport.objects
        .filter(
            reported_user=account
        )
    )

    total_user_reports = (
        user_reports.count()
    )

    pending_user_reports = (
        user_reports
        .filter(
            status__in=(
                UserReport.Status.PENDING,
                UserReport.Status.REVIEWING,
            )
        )
        .count()
    )

    rejected_user_reports = (
        user_reports
        .filter(
            status=(
                UserReport.Status.REJECTED
            )
        )
        .count()
    )

    confirmed_user_reports = (
        user_reports
        .filter(
            status=(
                UserReport.Status.RESOLVED
            )
        )
        .count()
    )

    last_violation = (
        violations.first()
    )

    abuse_attempts = (
        AbuseAttempt.objects
        .filter(
            user=account
        )
        .order_by(
            "-created_at",
            "-pk",
        )
    )

    now = timezone.now()

    abuse_attempts_24h = (
        abuse_attempts
        .filter(
            created_at__gte=(
                now
                - timedelta(
                    hours=24
                )
            )
        )
        .count()
    )

    abuse_attempts_7d = (
        abuse_attempts
        .filter(
            created_at__gte=(
                now
                - timedelta(
                    days=7
                )
            )
        )
        .count()
    )

    if violation_count == 0:
        risk_level = "Normal"
        risk_code = "NORMAL"

    elif violation_count == 1:
        risk_level = "Uyarı"
        risk_code = "WARNING"

    elif violation_count == 2:
        risk_level = (
            "Tekrarlanan ihlal"
        )
        risk_code = "REPEATED"

    elif violation_count < 5:
        risk_level = (
            "Yüksek risk"
        )
        risk_code = "HIGH"

    else:
        risk_level = (
            "Askıya almaya uygun"
        )
        risk_code = (
            "SUSPEND_ELIGIBLE"
        )

    suspension_eligible = (
        violation_count >= 5
    )

    return render(
        request,
        "adminx/user_detail.html",
        {
            "account":
                account,

            "violation_count":
                violation_count,

            "last_violation":
                last_violation,

            "recent_violations":
                violations[:10],

            "total_user_reports":
                total_user_reports,

            "pending_user_reports":
                pending_user_reports,

            "confirmed_user_reports":
                confirmed_user_reports,

            "rejected_user_reports":
                rejected_user_reports,

            "risk_level":
                risk_level,

            "risk_code":
                risk_code,

            "suspension_eligible":
                suspension_eligible,

            "abuse_attempts_24h":
                abuse_attempts_24h,

            "abuse_attempts_7d":
                abuse_attempts_7d,

            "recent_abuse_attempts":
                abuse_attempts[:10],
        },
    )


@admin_required
@require_safe
def security_event_list(
    request,
):
    events = (
        AbuseAttempt.objects
        .select_related(
            "user"
        )
        .order_by(
            "-created_at",
            "-pk",
        )
    )

    search = (
        request.GET
        .get(
            "q",
            "",
        )
        .strip()[:100]
    )

    event_type = (
        request.GET
        .get(
            "event_type",
            "",
        )
        .strip()
    )

    if search:
        events = events.filter(
            Q(
                user__username__icontains=search
            )
            | Q(
                user__email__icontains=search
            )
            | Q(
                ip_address__icontains=search
            )
            | Q(
                detail__icontains=search
            )
        )

    valid_event_types = {
        value
        for (
            value,
            _label,
        )
        in AbuseAttempt.EventType.choices
    }

    if (
        event_type
        in valid_event_types
    ):
        events = events.filter(
            event_type=event_type
        )

    else:
        event_type = ""

    page_obj = paginate(
        request,
        events,
        "admin",
    )

    return render(
        request,
        "adminx/security_event_list.html",
        {
            "page_obj":
                page_obj,

            "search":
                search,

            "active_event_type":
                event_type,

            "event_type_choices":
                AbuseAttempt.EventType.choices,
        },
    )


@admin_required
@require_safe
def security_event_detail(
    request,
    pk,
):
    event = get_object_or_404(
        AbuseAttempt.objects
        .select_related(
            "user"
        ),
        pk=pk,
    )

    metadata = (
        event.metadata
        or {}
    )

    company = None

    company_id = (
        metadata.get(
            "company_id"
        )
    )

    if company_id:
        company = (
            Company.objects
            .filter(
                pk=company_id
            )
            .only(
                "pk",
                "name",
            )
            .first()
        )

    related_complaint = None

    related_complaint_id = (
        metadata.get(
            "matched_complaint_id"
        )
        or metadata.get(
            "previous_complaint_id"
        )
    )

    if related_complaint_id:
        related_complaint = (
            Complaint.objects
            .select_related(
                "company",
                "user",
            )
            .filter(
                pk=related_complaint_id
            )
            .first()
        )

        if (
            not company
            and related_complaint
        ):
            company = (
                related_complaint.company
            )

    similarity_percent = None

    similarity = (
        metadata.get(
            "similarity"
        )
    )

    if similarity is not None:
        try:
            similarity_percent = round(
                float(
                    similarity
                )
                * 100,
                1,
            )

        except (
            TypeError,
            ValueError,
        ):
            similarity_percent = None

    limit_value = (
        metadata.get(
            "limit"
        )
        or metadata.get(
            "daily_limit"
        )
    )

    observed_value = (
        metadata.get(
            "complaints_last_10m"
        )
        or metadata.get(
            "complaints_last_1h"
        )
        or metadata.get(
            "complaints_last_24h"
        )
        or metadata.get(
            "open_complaint_count"
        )
        or metadata.get(
            "rejected_last_10_days"
        )
    )

    restriction_until = (
        metadata.get(
            "restriction_until"
        )
        or metadata.get(
            "next_allowed_at"
        )
    )

    return render(
        request,
        "adminx/security_event_detail.html",
        {
            "event":
                event,

            "company":
                company,

            "related_complaint":
                related_complaint,

            "similarity_percent":
                similarity_percent,

            "limit_value":
                limit_value,

            "observed_value":
                observed_value,

            "restriction_until":
                restriction_until,
        },
    )


@admin_required
@require_safe
def homepage_content(
    request,
):
    return render(
        request,
        "adminx/homepage_content.html",
        {
            "hero_brand_messages":
                HERO_BRAND_MESSAGES
        },
    )


@admin_required
@require_POST
def company_archive(
    request,
    pk,
):
    changed = archive_company(
        pk=pk,
        actor=request.user,
    )

    if changed:
        messages.success(
            request,
            (
                "Şirket arşivlendi. "
                "Public görünürlüğü ve "
                "bu şirkete erişim kapatıldı."
            ),
        )

    else:
        messages.info(
            request,
            (
                "Bu şirket daha önce "
                "arşivlenmiş."
            ),
        )

    return redirect(
        "adminx:company_edit",
        pk=pk,
    )