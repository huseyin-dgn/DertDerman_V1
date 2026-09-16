from django.db.models import (
    Count,
    Exists,
    OuterRef,
    Q,
)
from django.shortcuts import render
from django.views.decorators.http import (
    require_safe,
)

from accounts.models import User
from complaints.models import (
    Complaint,
    DermanPost,
    DermanReaction,
)
from core.decorators import role_required
from core.pagination import (
    PREVIEW_SIZE,
    paginate,
)


@role_required(
    User.UserType.USER
)
@require_safe
def home(request):
    from companies.models import (
        CompanyResponse,
    )

    from notifications.selectors import (
        inbox,
    )

    response_exists = (
        CompanyResponse.objects
        .filter(
            complaint_id=OuterRef(
                "pk"
            ),
            company_id=OuterRef(
                "company_id"
            ),
            is_active=True,
        )
    )

    complaints = (
        Complaint.objects
        .filter(
            user=request.user
        )
        .select_related(
            "company"
        )
        .annotate(
            has_response=Exists(
                response_exists
            )
        )
    )

    counts = complaints.aggregate(
        total=Count(
            "pk"
        ),
        pending=Count(
            "pk",
            filter=Q(
                status=(
                    Complaint.Status.PENDING
                )
            ),
        ),
        answered=Count(
            "pk",
            filter=Q(
                has_response=True
            ),
        ),
        resolved=Count(
            "pk",
            filter=Q(
                status=(
                    Complaint.Status.RESOLVED
                )
            ),
        ),
    )

    recent_complaints = (
        complaints
        .select_related(
            "company"
        )
        .order_by(
            "-created_at",
            "-pk",
        )[:PREVIEW_SIZE]
    )

    notifications = inbox(
        request.user,
        "USER",
    )

    return render(
        request,
        "dashboard/home.html",
        {
            "recent_complaints":
                recent_complaints,

            "recent_notifications":
                notifications[
                    :PREVIEW_SIZE
                ],

            "metrics": {
                **counts,

                "unread":
                    notifications
                    .filter(
                        is_read=False
                    )
                    .count(),
            },
        },
    )


@role_required(
    User.UserType.USER
)
@require_safe
def dermans(request):
    base_queryset = (
        DermanPost.objects
        .filter(
            author_user=request.user
        )
        .select_related(
            "complaint",
            "complaint__company",
        )
    )

    metrics = (
        base_queryset
        .aggregate(
            total=Count(
                "pk"
            ),

            published=Count(
                "pk",
                filter=Q(
                    status=(
                        DermanPost
                        .Status
                        .PUBLISHED
                    )
                ),
            ),

            pending=Count(
                "pk",
                filter=Q(
                    status=(
                        DermanPost
                        .Status
                        .PENDING
                    )
                ),
            ),

            withdrawn=Count(
                "pk",
                filter=Q(
                    status=(
                        DermanPost
                        .Status
                        .WITHDRAWN
                    )
                ),
            ),
        )
    )

    active_status = (
        request.GET.get(
            "status",
            "all",
        )
        .strip()
        .upper()
    )

    valid_statuses = set(
        DermanPost.Status.values
    )

    queryset = (
        base_queryset
        .annotate(
            like_count=Count(
                "reactions",
                filter=Q(
                    reactions__reaction_type=(
                        DermanReaction
                        .Type
                        .LIKE
                    )
                ),
                distinct=True,
            ),

            dislike_count=Count(
                "reactions",
                filter=Q(
                    reactions__reaction_type=(
                        DermanReaction
                        .Type
                        .DISLIKE
                    )
                ),
                distinct=True,
            ),
        )
        .order_by(
            "-created_at",
            "-pk",
        )
    )

    if (
        active_status != "ALL"
        and active_status
        in valid_statuses
    ):
        queryset = (
            queryset.filter(
                status=active_status
            )
        )
    else:
        active_status = "ALL"

    page_obj = paginate(
        request,
        queryset,
        "user_dermans",
    )

    return render(
        request,
        "dashboard/dermans.html",
        {
            "page_obj":
                page_obj,

            "metrics":
                metrics,

            "active_status":
                active_status,

            "status_options":
                DermanPost
                .Status
                .choices,
        },
    )