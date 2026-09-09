from django.contrib import messages
from datetime import timedelta
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe
from complaints.models import Complaint
from companies.models import Company
from accounts.models import User
from blog.models import Post
from companies.models import CompanyNotification
from core.pagination import PREVIEW_SIZE, paginate
from notifications.selectors import inbox
from notifications.services import mark_read
from .filters import ComplaintFilters, EventFilters, list_context
from .decorators import admin_required


@admin_required
@require_safe
def home(request):
    pending_count = Complaint.objects.filter(status=Complaint.Status.PENDING).count()
    pending_company_count = Company.objects.filter(
        approval_status=Company.ApprovalStatus.PENDING
    ).count()
    counts = Complaint.objects.aggregate(
        published=Count("pk", filter=Q(status=Complaint.Status.PUBLISHED)),
        resolved=Count("pk", filter=Q(status=Complaint.Status.RESOLVED)),
    )
    return render(
        request,
        "adminx/home.html",
        {
            "pending_count": pending_count,
            "recent_notifications": inbox(request.user, 'ADMIN')[:PREVIEW_SIZE],
            "pending_company_count": pending_company_count,
            "user_count": User.objects.count(),
            "company_count": Company.objects.count(),
            "published_count": counts["published"],
            "resolved_count": counts["resolved"],
            "blog_count": Post.objects.filter(status=Post.Status.PUBLISHED).count(),
            "activity_count": CompanyNotification.objects.filter(created_at__gte=timezone.now() - timedelta(days=7)).count(),
            "recent_complaints": _moderation_complaints().order_by("-created_at", "-pk")[:PREVIEW_SIZE],
            "recent_applications": Company.objects.filter(approval_status=Company.ApprovalStatus.PENDING).order_by("-created_at", "-pk")[:PREVIEW_SIZE],
            "recent_users": User.objects.only("username", "first_name", "last_name", "date_joined", "user_type").order_by("-date_joined", "-pk")[:PREVIEW_SIZE],
            "recent_posts": Post.objects.filter(status=Post.Status.PUBLISHED).defer("content").order_by("-published_at", "-pk")[:PREVIEW_SIZE],
        },
    )

def _moderation_complaints():
    return Complaint.objects.select_related("company", "user").only(
        "company__name", "user__username", "title", "description", "status",
        "created_at", "updated_at",
    )


@admin_required
@require_safe
def complaint_list(request):
    context = list_context(request, _moderation_complaints(), ComplaintFilters,
        search_fields=("title", "user__username", "company__name"),
        fields={"status": "status", "company": "company"}, defaults={"status": Complaint.Status.PENDING})
    context["complaints"] = context["page_obj"]
    return render(request, "adminx/complaint_list.html", context)


@admin_required
@require_safe
def notifications(request):
    return render(request, 'notifications/admin_list.html', {
        'page_obj': paginate(request, inbox(request.user, 'ADMIN'), 'admin_notifications')})


@admin_required
@require_POST
def notification_read(request, pk):
    notification = get_object_or_404(inbox(request.user, 'ADMIN'), pk=pk)
    mark_read(inbox(request.user, 'ADMIN').filter(pk=notification.pk))
    return redirect('adminx:notifications')


@admin_required
@require_safe
def notification_open(request, pk):
    notification = get_object_or_404(inbox(request.user, 'ADMIN'), pk=pk)
    return redirect(notification.target_url)


@admin_required
@require_POST
def notifications_read_all(request):
    mark_read(inbox(request.user, 'ADMIN'))
    return redirect('adminx:notifications')


@admin_required
@require_safe
def activity(request):
    return _event_list(request, "activity")


def _event_list(request, kind):
    context = list_context(request, CompanyNotification.objects.select_related("company", "complaint"),
        EventFilters, search_fields=("title", "company__name"), fields={"kind": "kind"})
    context["is_activity"] = kind == "activity"
    return render(request, "adminx/event_list.html", context)


@admin_required
@require_safe
def complaint_detail(request, pk):
    complaint = get_object_or_404(_moderation_complaints(), pk=pk)
    return render(request, "adminx/complaint_detail.html", {"complaint": complaint})


@transaction.atomic
def _moderate(request, pk, target_status):
    get_object_or_404(Complaint.objects.only("pk"), pk=pk)
    changed = Complaint.objects.filter(pk=pk, status=Complaint.Status.PENDING).update(
        status=target_status, updated_at=timezone.now()
    )
    if not changed:
        complaint = get_object_or_404(_moderation_complaints(), pk=pk)
        return render(request, "adminx/complaint_detail.html", {
            "complaint": complaint,
            "moderation_error": "Bu şikayet artık incelemede değil. Karar uygulanmadı.",
        }, status=409)
    from companies.models import CompanyNotification
    from companies.panel_events import record_complaint_notification
    complaint = Complaint.objects.only("company_id").get(pk=pk)
    record_complaint_notification(complaint,
        CompanyNotification.Kind.PUBLISHED if target_status == Complaint.Status.PUBLISHED else CompanyNotification.Kind.ADMIN)
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
