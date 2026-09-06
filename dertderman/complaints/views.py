from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_safe

from accounts.models import User
from core.decorators import role_required

from .forms import ComplaintCreateForm
from .models import Complaint


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
                "Şikayetiniz alındı. İncelendikten sonra yayınlanacaktır.",
            )
            return redirect("dashboard:home")
    else:
        form = ComplaintCreateForm()

    return render(request, "complaints/complaint_create.html", {"form": form})
