from django import template
from django.db.models import Count, Q

from accounts.models import User
from complaints.models import UserViolation


register = template.Library()


@register.simple_tag
def permanent_close_alerts(limit=10):
    rows = (
        UserViolation.objects
        .filter(
            user__user_type=User.UserType.USER,
            user__is_active=True,
            user__is_permanently_closed=False,
            source_type=UserViolation.SourceType.FALSE_REPORT,
        )
        .values(
            "user_id",
            "user__username",
            "user__first_name",
            "user__last_name",
        )
        .annotate(
            total_count=Count("id"),
            user_report_count=Count(
                "id",
                filter=Q(user_report__isnull=False),
            ),
            content_report_count=Count(
                "id",
                filter=Q(content_report__isnull=False),
            ),
            company_report_count=Count(
                "id",
                filter=Q(company_report__isnull=False),
            ),
        )
        .filter(
            Q(user_report_count__gte=4)
            | Q(content_report_count__gte=4)
            | Q(company_report_count__gte=4)
            | Q(total_count__gte=9)
        )
        .order_by(
            "-total_count",
            "user__username",
        )[:limit]
    )

    return list(rows)
