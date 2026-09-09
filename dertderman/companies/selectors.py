from .models import Company


def public_companies():
    # Verification is a badge, not a prerequisite for the public directory.
    return Company.objects.filter(
        is_active=True, approval_status=Company.ApprovalStatus.APPROVED,
        archived_at__isnull=True,
    ).select_related("category").order_by("-created_at", "-pk")
