from django.core.exceptions import PermissionDenied
from django.db.models import Count

from complaints.models import Complaint
from notifications.models import Notification
from notifications.selectors import inbox

from .permissions import is_valid_private_user


def _require_private_user(user) -> None:
    if not is_valid_private_user(user):
        raise PermissionDenied


def get_my_complaint_summary(user) -> dict:
    _require_private_user(user)

    complaints = Complaint.objects.filter(user=user)

    counts_by_status = {
        row["status"]: row["total"]
        for row in (
            complaints
            .values("status")
            .annotate(total=Count("pk"))
        )
    }

    status_distribution = [
        {
            "status": status,
            "label": label,
            "count": counts_by_status.get(status, 0),
        }
        for status, label in Complaint.Status.choices
    ]

    latest = (
        complaints
        .select_related("company")
        .only(
            "pk",
            "title",
            "status",
            "created_at",
            "company__name",
        )
        .order_by("-created_at", "-pk")
        .first()
    )

    latest_data = None
    if latest is not None:
        latest_data = {
            "id": latest.pk,
            "title": latest.title,
            "status": latest.status,
            "company_name": latest.company.name,
            "created_at": latest.created_at,
        }

    return {
        "total": sum(counts_by_status.values()),
        "status_distribution": status_distribution,
        "latest": latest_data,
    }


def get_my_notification_summary(user) -> dict:
    _require_private_user(user)

    notifications = inbox(
        user,
        Notification.Scope.USER,
    )

    return {
        "unread_count": notifications.filter(
            is_read=False
        ).count(),
    }


def get_my_summary(user) -> dict:
    _require_private_user(user)

    return {
        "complaints": get_my_complaint_summary(user),
        "notifications": get_my_notification_summary(user),
    }
