from django.db.models import DateTimeField, OuterRef, Subquery
from django.db.models.functions import Coalesce

from complaints.models import Complaint, ComplaintEvent

from .models import Company, CompanyResponse


def public_companies():
    # Verification is a badge, not a prerequisite for the public directory.
    return Company.objects.filter(
        is_active=True, approval_status=Company.ApprovalStatus.APPROVED,
        archived_at__isnull=True,
    ).select_related("category").order_by("-created_at", "-pk")


def public_company_performance(company):
    """Return public performance data with one annotated complaint query."""
    first_response = CompanyResponse.objects.filter(
        complaint_id=OuterRef("pk"),
        company_id=OuterRef("company_id"),
        is_active=True,
    ).order_by("created_at", "pk")
    published_event = ComplaintEvent.objects.filter(
        complaint_id=OuterRef("pk"),
        event_type=ComplaintEvent.Type.PUBLISHED,
    ).order_by("occurred_at", "pk")
    rows = (
        Complaint.objects.filter(
            company=company,
            status__in=(Complaint.Status.PUBLISHED, Complaint.Status.RESOLVED),
            withdrawn_at__isnull=True,
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
        .values_list("status", "created_at", "published_at", "first_response_at")
    )

    total = answered = resolved = 0
    response_seconds = []
    for status, created_at, published_at, first_response_at in rows:
        total += 1
        resolved += status == Complaint.Status.RESOLVED
        if first_response_at is None:
            continue
        answered += 1
        # Legacy/imported data can contain a reply predating its publication event.
        started_at = published_at if first_response_at >= published_at else created_at
        if first_response_at >= started_at:
            response_seconds.append((first_response_at - started_at).total_seconds())

    return {
        "total": total,
        "answered": answered,
        "resolved": resolved,
        "response_ratio": round(answered * 100 / total) if total else None,
        "resolved_ratio": round(resolved * 100 / total) if total else None,
        "average_response_seconds": (
            sum(response_seconds) / len(response_seconds) if response_seconds else None
        ),
    }
