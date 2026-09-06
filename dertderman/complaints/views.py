from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_safe

from accounts.models import User
from core.decorators import role_required

from .forms import ComplaintCreateForm
from .models import Complaint
from .selectors import public_complaints


@require_safe
def public_complaint_list(request):
    page_obj = Paginator(public_complaints(), 12).get_page(request.GET.get("page"))
    return render(request, "complaints/public_list.html", {"page_obj": page_obj})


@require_safe
def public_complaint_detail(request, pk):
    complaint = get_object_or_404(public_complaints(), pk=pk)
    return render(request, "complaints/public_detail.html", {"complaint": complaint})


@role_required(User.UserType.USER)
@require_safe
def complaint_list(request):
    complaints = (
        Complaint.objects.filter(user=request.user)
        .select_related("company")
        .order_by("-created_at", "-pk")
    )
    return render(request, "complaints/complaint_list.html", {"complaints": complaints})


@role_required(User.UserType.USER)
@require_safe
def complaint_detail(request, pk):
    complaint = get_object_or_404(
        Complaint.objects.select_related("company"), pk=pk, user=request.user
    )
    return render(request, "complaints/complaint_detail.html", {"complaint": complaint})


@role_required(User.UserType.USER)
def complaint_create(request):
    if request.method == "POST":
        form = ComplaintCreateForm(request.POST)
        if form.is_valid():
            complaint = form.save(commit=False)
            complaint.user = request.user
            complaint.status = Complaint.Status.PENDING
            complaint.save()
            messages.success(
                request,
                "Şikayetiniz incelemeye alındı. Yayınlanmadan önce değerlendirilecektir.",
            )
            return redirect("dashboard:home")
    else:
        form = ComplaintCreateForm()

    return render(request, "complaints/complaint_create.html", {"form": form})
