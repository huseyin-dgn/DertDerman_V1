from django.db.models import CharField, DateTimeField, Exists, F, OuterRef, Q, Subquery, Value
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
    from .services import active_company_memberships_for
    if not user.is_authenticated or not user.is_active or user.user_type != 'COMPANY':
        return CompanyNotification.objects.none()
    reads = CompanyNotificationRead.objects.filter(notification_id=OuterRef("pk"), user=user)
    return CompanyNotification.objects.filter(company=company,
        company_id__in=active_company_memberships_for(user).values('company_id')).filter(
        Q(complaint__isnull=True) | Q(complaint__company=company),
    ).select_related("complaint", "company").annotate(is_read=Exists(reads))


def complaint_history(company, user, complaint):
    """Union in SQL so the whole history stays reachable without loading it all."""
    def events(queryset, source, title):
        return queryset.order_by().annotate(
            at=F("created_at"), event_title=title, event_id=F("pk"),
            source=Value(source, output_field=CharField()),
        ).values("at", "event_title", "event_id", "source")

    created = events(Complaint.objects.filter(pk=complaint.pk, company=company), "complaint", Value("Şikayet oluşturuldu"))
    responses = events(company_responses(company).filter(complaint=complaint), "response", Value("Şirket cevabı eklendi"))
    notes = events(company_notes(company).filter(complaint=complaint), "note", Value("Dahili not eklendi"))
    notifications = events(company_notifications(company, user).filter(complaint=complaint).exclude(kind="NEW"), "notification", F("title"))
    return created.union(responses, notes, notifications, all=True).order_by("-at", "-source", "-event_id")
