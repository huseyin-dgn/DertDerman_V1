from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_safe

from accounts.models import User
from companies.models import Company
from companies.services import decide_company_application
from .decorators import admin_required
from core.presentation import HERO_BRAND_MESSAGES
from .forms import CompanyApprovalActionForm, CompanyContentForm


@admin_required
@require_safe
def company_list(request):
    page_obj = Paginator(Company.objects.only("name", "slug", "is_active").order_by("name", "pk"), 20).get_page(request.GET.get("page"))
    return render(request, "adminx/company_list.html", {"page_obj": page_obj})


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
    applications = (
        Company.objects.prefetch_related("memberships__user")
        .order_by("approval_status", "-created_at", "-pk")
    )
    return render(
        request,
        "adminx/company_application_list.html",
        {"applications": applications},
    )


@admin_required
@require_http_methods(["GET", "HEAD", "POST"])
def company_application_detail(request, pk):
    company = get_object_or_404(
        Company.objects.prefetch_related("memberships__user"),
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
        {"company": company, "form": form, "decision_error": decision_error},
        status=409 if decision_error else 200,
    )


@admin_required
@require_safe
def user_list(request):
    users = User.objects.only("username", "email", "user_type", "is_active").order_by("username", "pk")
    return render(request, "adminx/user_list.html", {"page_obj": Paginator(users, 20).get_page(request.GET.get("page"))})


@admin_required
@require_safe
def homepage_content(request):
    return render(request, "adminx/homepage_content.html", {"hero_brand_messages": HERO_BRAND_MESSAGES})
