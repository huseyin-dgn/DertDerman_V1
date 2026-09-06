from .models import Complaint


def public_complaints():
    # RESOLVED does not establish prior publication in the current model.
    # Match the public company domain: inactive companies are not exposed.
    return (
        Complaint.objects.filter(
            status=Complaint.Status.PUBLISHED, company__is_active=True
        )
        .select_related("company")
        .order_by("-created_at", "-pk")
    )
