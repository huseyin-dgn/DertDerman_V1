from django.db import transaction
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import get_object_or_404

from complaints.models import Complaint
from .models import CompanyResponse, InternalCompanyNote
from .panel_permissions import require_company_membership


@transaction.atomic
def create_company_entry(*, user, company_id, complaint_id, body, internal=False):
    # Recheck access here too: callers cannot supply company/author via form data.
    membership = require_company_membership(user, company_id)
    complaint = get_object_or_404(
        Complaint.objects.select_for_update().filter(company_id=membership.company_id), pk=complaint_id,
    )
    model = InternalCompanyNote if internal else CompanyResponse
    if not internal:
        # A quick retry of an identical form is one response/event. Later replies
        # remain legitimate, even when their text matches a previous response.
        existing = model.objects.filter(complaint=complaint, company=membership.company,
            author_user=user, body=body.strip(), is_active=True,
            created_at__gte=timezone.now() - timedelta(seconds=30)).first()
        if existing:
            return existing
    entry = model(complaint=complaint, company=membership.company, author_user=user, body=body)
    entry.save()  # Model validation also enforces matching complaint/company and nonempty content.
    return entry
