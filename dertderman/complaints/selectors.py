from django.db.models import Count, Exists, F, OuterRef, Q

from companies.models import CompanyResponse

from .models import Complaint


def public_complaints():
    # A resolved complaint remains part of the public record after publication.
    return (
        Complaint.objects.filter(
            status__in=(Complaint.Status.PUBLISHED, Complaint.Status.RESOLVED),
            company__is_active=True,
            withdrawn_at__isnull=True,
        )
        .select_related("company")
        .annotate(
            author_username=F("user__username"),
            author_first_name=F("user__first_name"),
            author_selected_avatar=F("user__selected_avatar"),
            like_count=Count("likes", distinct=True),
            reaction_count=Count("reactions", distinct=True),
            comment_count=Count(
                "comments", filter=Q(comments__is_active=True), distinct=True
            ),
            has_response=Exists(
                CompanyResponse.objects.filter(
                    complaint_id=OuterRef("pk"),
                    company_id=OuterRef("company_id"),
                    is_active=True,
                )
            ),
        )
        .order_by("-created_at", "-pk")
    )
