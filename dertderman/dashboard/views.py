from django.shortcuts import render
from django.db.models import Count, Exists, OuterRef, Q

from accounts.models import User
from complaints.models import Complaint
from core.decorators import role_required
from core.pagination import PREVIEW_SIZE


@role_required(User.UserType.USER)
def home(request):
    from companies.models import CompanyResponse
    from notifications.selectors import inbox

    response_exists = CompanyResponse.objects.filter(
        complaint_id=OuterRef("pk"), company_id=OuterRef("company_id"), is_active=True
    )
    complaints = Complaint.objects.filter(user=request.user).select_related("company").annotate(
        has_response=Exists(response_exists)
    )
    counts = complaints.aggregate(
        total=Count("pk"),
        pending=Count("pk", filter=Q(status=Complaint.Status.PENDING)),
        answered=Count("pk", filter=Q(has_response=True)),
        resolved=Count("pk", filter=Q(status=Complaint.Status.RESOLVED)),
    )
    recent_complaints = (
        complaints
        .select_related("company")
        .order_by("-created_at", "-pk")[:PREVIEW_SIZE]
    )
    notifications = inbox(request.user, "USER")
    return render(
        request,
        "dashboard/home.html",
        {
            "recent_complaints": recent_complaints,
            "recent_notifications": notifications[:PREVIEW_SIZE],
            "metrics": {**counts, "unread": notifications.filter(is_read=False).count()},
        },
    )
