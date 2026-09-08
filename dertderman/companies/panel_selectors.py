from django.db.models import DateTimeField, Exists, F, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce, Greatest

from complaints.models import Complaint
from .models import CompanyNotification, CompanyNotificationRead, CompanyResponse, InternalCompanyNote


def company_responses(company):
    return CompanyResponse.objects.filter(company=company, complaint__company=company, is_active=True).select_related("complaint", "author_user")


def company_notes(company):
    return InternalCompanyNote.objects.filter(company=company, complaint__company=company).select_related("author_user")


def company_complaints(company):
    responses = company_responses(company).filter(complaint_id=OuterRef("pk"))
    notes = company_notes(company).filter(complaint_id=OuterRef("pk"))
    return Complaint.objects.filter(company=company).select_related("user", "company").annotate(
        has_response=Exists(responses),
        first_response_at=Subquery(responses.order_by("created_at", "pk").values("created_at")[:1], output_field=DateTimeField()),
        last_response_at=Subquery(responses.values("created_at")[:1], output_field=DateTimeField()),
        last_note_at=Subquery(notes.values("created_at")[:1], output_field=DateTimeField()),
    ).annotate(last_activity=Greatest(
        F("updated_at"), Coalesce("last_response_at", "created_at"), Coalesce("last_note_at", "created_at"),
    )).order_by("-created_at", "-pk")


def company_notifications(company, user):
    reads = CompanyNotificationRead.objects.filter(notification_id=OuterRef("pk"), user=user)
    return CompanyNotification.objects.filter(company=company).filter(
        Q(complaint__isnull=True) | Q(complaint__company=company),
    ).select_related("complaint").annotate(is_read=Exists(reads))
