from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_safe

from accounts.models import User
from companies.models import Company
from .decorators import admin_required
from core.presentation import HERO_BRAND_MESSAGES
from .forms import CompanyContentForm


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
def user_list(request):
    users = User.objects.only("username", "email", "user_type", "is_active").order_by("username", "pk")
    return render(request, "adminx/user_list.html", {"page_obj": Paginator(users, 20).get_page(request.GET.get("page"))})


@admin_required
@require_safe
def homepage_content(request):
    return render(request, "adminx/homepage_content.html", {"hero_brand_messages": HERO_BRAND_MESSAGES})
