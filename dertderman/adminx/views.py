from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe

from complaints.models import Complaint
from .decorators import admin_required


@admin_required
@require_safe
def home(request):
    pending_count = Complaint.objects.filter(status=Complaint.Status.PENDING).count()
    return render(request, "adminx/home.html", {"pending_count": pending_count})


def _moderation_complaints():
    return Complaint.objects.select_related("company", "user").only(
        "company__name", "user__username", "title", "description", "status",
        "created_at", "updated_at",
    )


@admin_required
@require_safe
def complaint_list(request):
    complaints = _moderation_complaints().filter(
        status=Complaint.Status.PENDING
    ).order_by("-created_at", "-pk")
    return render(request, "adminx/complaint_list.html", {"complaints": complaints})


@admin_required
@require_safe
def complaint_detail(request, pk):
    complaint = get_object_or_404(_moderation_complaints(), pk=pk)
    return render(request, "adminx/complaint_detail.html", {"complaint": complaint})


def _moderate(request, pk, target_status):
    get_object_or_404(Complaint.objects.only("pk"), pk=pk)
    # A single conditional UPDATE prevents a stale review or double submit
    # from overwriting another moderation decision, including on SQLite.
    changed = Complaint.objects.filter(pk=pk, status=Complaint.Status.PENDING).update(
        status=target_status, updated_at=timezone.now()
    )
    if not changed:
        complaint = get_object_or_404(_moderation_complaints(), pk=pk)
        return render(request, "adminx/complaint_detail.html", {
            "complaint": complaint,
            "moderation_error": "Bu şikayet artık incelemede değil. Karar uygulanmadı.",
        }, status=409)
    messages.success(request, (
        "Şikayet yayınlandı." if target_status == Complaint.Status.PUBLISHED
        else "Şikayet reddedildi."
    ))
    return redirect("adminx:complaint_detail", pk=pk)


@admin_required
@require_POST
def complaint_publish(request, pk):
    return _moderate(request, pk, Complaint.Status.PUBLISHED)


@admin_required
@require_POST
def complaint_reject(request, pk):
    return _moderate(request, pk, Complaint.Status.REJECTED)
