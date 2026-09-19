from django.db.models import (
    Count,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce

from companies.models import (
    Company,
    CompanyResponse,
)

from .models import (
    Complaint,
    ComplaintComment,
    ComplaintLike,
    ComplaintReaction,
)


def public_complaint_filter():
    """Single source of truth for records that may be exposed publicly."""
    return Q(
        status__in=(
            Complaint.Status.PUBLISHED,
            Complaint.Status.RESOLVED,
        ),
        withdrawn_at__isnull=True,
        removed_for_violation=False,
        violation_removed_at__isnull=True,
        company__is_active=True,
        company__approval_status=Company.ApprovalStatus.APPROVED,
        company__archived_at__isnull=True,
    )


def public_complaint_records():
    return Complaint.objects.filter(public_complaint_filter())


def public_complaints_for_update():
    """Lockable public queryset without aggregates that PostgreSQL rejects."""
    return (
        public_complaint_records()
        .select_for_update(of=("self",))
        .select_related("company", "user")
    )


def public_complaint_cards():
    """
    Lightweight queryset for public complaint cards/lists.

    Aggregate counts are calculated only for rows selected by
    pagination/LIMIT instead of joining and grouping the entire
    public complaint dataset.
    """

    like_count_query = (
        ComplaintLike.objects
        .filter(
            complaint_id=OuterRef("pk")
        )
        .order_by()
        .values(
            "complaint_id"
        )
        .annotate(
            total=Count("pk")
        )
        .values(
            "total"
        )[:1]
    )

    reaction_count_query = (
        ComplaintReaction.objects
        .filter(
            complaint_id=OuterRef("pk")
        )
        .order_by()
        .values(
            "complaint_id"
        )
        .annotate(
            total=Count("pk")
        )
        .values(
            "total"
        )[:1]
    )

    comment_count_query = (
        ComplaintComment.objects
        .filter(
            complaint_id=OuterRef("pk"),
            is_active=True,
        )
        .order_by()
        .values(
            "complaint_id"
        )
        .annotate(
            total=Count("pk")
        )
        .values(
            "total"
        )[:1]
    )

    response_query = (
        CompanyResponse.objects
        .filter(
            complaint_id=OuterRef("pk"),
            company_id=OuterRef(
                "company_id"
            ),
            is_active=True,
        )
    )

    return (
        public_complaint_records()
        .select_related(
            "company",
        )
        .annotate(
            author_username=F(
                "user__username"
            ),

            author_first_name=F(
                "user__first_name"
            ),

            author_selected_avatar=F(
                "user__selected_avatar"
            ),

            like_count=Coalesce(
                Subquery(
                    like_count_query,
                    output_field=(
                        IntegerField()
                    ),
                ),
                Value(0),
            ),

            reaction_count=Coalesce(
                Subquery(
                    reaction_count_query,
                    output_field=(
                        IntegerField()
                    ),
                ),
                Value(0),
            ),

            comment_count=Coalesce(
                Subquery(
                    comment_count_query,
                    output_field=(
                        IntegerField()
                    ),
                ),
                Value(0),
            ),

            has_response=Exists(
                response_query
            ),
        )
        .order_by(
            "-created_at",
            "-pk",
        )
    )


def public_complaints():
    return (
        public_complaint_records()
        .select_related(
            "company",
            "company__category",
            "user",
        )
        .annotate(
            author_username=F(
                "user__username"
            ),

            author_first_name=F(
                "user__first_name"
            ),

            author_selected_avatar=F(
                "user__selected_avatar"
            ),

            like_count=Count(
                "likes",
                distinct=True,
            ),

            reaction_count=Count(
                "reactions",
                distinct=True,
            ),

            comment_count=Count(
                "comments",
                filter=Q(
                    comments__is_active=True
                ),
                distinct=True,
            ),

            has_response=Exists(
                CompanyResponse.objects
                .filter(
                    complaint_id=(
                        OuterRef("pk")
                    ),

                    company_id=(
                        OuterRef(
                            "company_id"
                        )
                    ),

                    is_active=True,
                )
            ),
        )
        .order_by(
            "-created_at",
            "-pk",
        )
    )
