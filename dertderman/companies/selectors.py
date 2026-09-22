from datetime import timezone as datetime_timezone

from django.db.models import (
    Case, Count, DateTimeField, DurationField, ExpressionWrapper,
    F, Max, Min, OuterRef, Q, Subquery, Sum, When,
)
from django.db.models.functions import Coalesce, TruncDate

from complaints.models import Complaint, ComplaintEvent

from .models import Company, CompanyResponse


def public_companies():
    # Verification is a badge, not a prerequisite for the public directory.
    return Company.objects.filter(
        is_active=True, approval_status=Company.ApprovalStatus.APPROVED,
        archived_at__isnull=True,
    ).select_related("category").order_by("-created_at", "-pk")


def public_company_performance(company):
    """Return public performance data without loading complaint rows."""
    first_response = CompanyResponse.objects.filter(
        complaint_id=OuterRef("pk"),
        company_id=OuterRef("company_id"),
        is_active=True,
    ).order_by("created_at", "pk")
    published_event = ComplaintEvent.objects.filter(
        complaint_id=OuterRef("pk"),
        event_type=ComplaintEvent.Type.PUBLISHED,
    ).order_by("occurred_at", "pk")
    metrics = (
        Complaint.objects.filter(
            company=company,
            status__in=(Complaint.Status.PUBLISHED, Complaint.Status.RESOLVED),
            withdrawn_at__isnull=True,
            removed_for_violation=False,
            violation_removed_at__isnull=True,
        )
        .annotate(
            first_response_at=Subquery(
                first_response.values("created_at")[:1],
                output_field=DateTimeField(),
            ),
            published_at=Coalesce(
                Subquery(
                    published_event.values("occurred_at")[:1],
                    output_field=DateTimeField(),
                ),
                "created_at",
            ),
        )
        .annotate(
            response_start_at=Case(
                When(first_response_at__gte=F("published_at"), then=F("published_at")),
                default=F("created_at"),
                output_field=DateTimeField(),
            ),
        )
        .annotate(
            response_duration=ExpressionWrapper(
                F("first_response_at") - F("response_start_at"),
                output_field=DurationField(),
            ),
        )
        .aggregate(
            total=Count("pk"),
            answered=Count("pk", filter=Q(first_response_at__isnull=False)),
            resolved=Count("pk", filter=Q(status=Complaint.Status.RESOLVED)),
            response_duration_total=Sum(
                "response_duration",
                filter=Q(first_response_at__gte=F("response_start_at")),
            ),
            response_duration_count=Count(
                "pk",
                filter=Q(first_response_at__gte=F("response_start_at")),
            ),
            response_activity_days=Count(
                TruncDate("first_response_at", tzinfo=datetime_timezone.utc),
                distinct=True,
            ),
            first_response_seen=Min("first_response_at"),
            last_response_seen=Max("first_response_at"),
        )
    )

    total = metrics["total"]
    answered = metrics["answered"]
    resolved = metrics["resolved"]
    response_duration_total = metrics["response_duration_total"]
    response_duration_count = metrics["response_duration_count"]
    first_response_seen = metrics["first_response_seen"]
    last_response_seen = metrics["last_response_seen"]

    return {
        "total": total,
        "answered": answered,
        "resolved": resolved,
        "response_ratio": round(answered * 100 / total) if total else None,
        "resolved_ratio": round(resolved * 100 / total) if total else None,
        "average_response_seconds": (
            response_duration_total.total_seconds() / response_duration_count
            if response_duration_count else None
        ),
        "response_activity_days": metrics["response_activity_days"],
        "response_span_days": (
            (last_response_seen - first_response_seen).days
            if first_response_seen and last_response_seen else 0
        ),
    }
