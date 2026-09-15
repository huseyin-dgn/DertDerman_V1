from django.db.models import (
    Count,
    Exists,
    F,
    OuterRef,
    Q,
)

from companies.models import (
    Company,
    CompanyResponse,
)

from .models import Complaint


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
