from django.contrib import messages
from django.core.exceptions import ValidationError
from core.pagination import PREVIEW_SIZE, paginate
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from complaints.models import Complaint
from .models import CompanyMembership, CompanyNotificationRead
from .panel_forms import CompanyProfileForm, CompanyResponseForm, ComplaintFilterForm, InternalCompanyNoteForm
from .panel_permissions import COMPANY_SESSION_KEY, PROFILE_ROLES, company_panel_required, require_profile_role
from .panel_selectors import company_complaints, company_notes, company_notifications, company_responses, complaint_history
from .panel_services import create_company_entry
from .services import get_accessible_company_membership


def panel_context(request, section, **extra):
    return {
        "company": request.company, "membership": request.company_membership,
        "memberships": request.company_memberships, "panel_section": section,
        "can_manage": request.company_membership.role in PROFILE_ROLES,
        "unread_count": company_notifications(request.company, request.user).filter(is_read=False).count(),
        **extra,
    }


def _dashboard(request):
    complaints = company_complaints(request.company)
    month_start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    metrics = complaints.aggregate(
        total=Count("pk"),
        waiting=Count("pk", filter=Q(has_response=False) & ~Q(status=Complaint.Status.RESOLVED)),
        answered=Count("pk", filter=Q(has_response=True)),
        resolved=Count("pk", filter=Q(status=Complaint.Status.RESOLVED)),
        this_month=Count("pk", filter=Q(created_at__gte=month_start)),
        average_response=Avg(ExpressionWrapper(F("first_response_at") - F("created_at"), output_field=DurationField())),
    )
    duration = metrics["average_response"]
    if duration is None:
        average_label = "—"
    else:
        minutes = max(0, int(duration.total_seconds() / 60))
        average_label = "< 1 dk" if minutes < 1 else f"{minutes} dk" if minutes < 60 else f"{minutes / 60:.1f} sa"
    return render(request, "companies/panel/dashboard.html", panel_context(request, "overview",
        metrics=metrics, average_label=average_label, recent_complaints=complaints[:PREVIEW_SIZE]))


@company_panel_required
@require_safe
def dashboard(request):
    return _dashboard(request)


@company_panel_required
@require_safe
def legacy_company_dashboard(request, slug):
    membership = get_accessible_company_membership(request.user, slug)
    request.company = membership.company
    request.company_membership = membership
    # Keep existing bookmarked company URLs working without exposing another company.
    request.session[COMPANY_SESSION_KEY] = membership.company_id
    return _dashboard(request)


@company_panel_required
@require_POST
def switch_company(request):
    membership = next((m for m in request.company_memberships if str(m.company_id) == request.POST.get("company_id")), None)
    if membership is None:
        from django.http import Http404
        raise Http404
    request.session[COMPANY_SESSION_KEY] = membership.company_id
    return redirect("companies:company_panel")


@company_panel_required
@require_safe
def complaint_list(request):
    form = ComplaintFilterForm(request.GET)
    complaints = company_complaints(request.company)
    if form.is_valid():
        data = form.cleaned_data
        if data["q"]:
            complaints = complaints.filter(Q(title__icontains=data["q"]) | Q(description__icontains=data["q"]))
        if data["state"] == "waiting":
            complaints = complaints.filter(has_response=False).exclude(status=Complaint.Status.RESOLVED)
        elif data["state"] == "answered":
            complaints = complaints.filter(has_response=True)
        elif data["state"] == "resolved":
            complaints = complaints.filter(status=Complaint.Status.RESOLVED)
        if data["start"]:
            complaints = complaints.filter(created_at__date__gte=data["start"])
        if data["end"]:
            complaints = complaints.filter(created_at__date__lte=data["end"])
    else:
        complaints = complaints.none()
    return render(request, "companies/panel/complaints.html", panel_context(request, "complaints",
        filter_form=form, page_obj=paginate(request, complaints, "company_complaints")))


def _detail_context(request, complaint, response_form=None, note_form=None):
    responses = company_responses(request.company).filter(complaint=complaint)
    notes = company_notes(request.company).filter(complaint=complaint)
    return panel_context(request, "complaints", complaint=complaint,
        response_form=response_form if response_form is not None else CompanyResponseForm(auto_id="response_%s"),
        note_form=note_form if note_form is not None else InternalCompanyNoteForm(auto_id="note_%s"),
        response_page=paginate(request, responses, "company_responses", page_param="response_page"),
        note_page=paginate(request, notes, "activity", page_param="note_page"),
        history=paginate(request, complaint_history(request.company, request.user, complaint), "activity", page_param="history_page"))


@company_panel_required
@require_safe
def complaint_detail(request, pk):
    complaint = get_object_or_404(company_complaints(request.company), pk=pk)
    return render(request, "companies/panel/complaint_detail.html", _detail_context(request, complaint))


def _create_entry(request, pk, internal):
    complaint = get_object_or_404(company_complaints(request.company), pk=pk)
    form_class = InternalCompanyNoteForm if internal else CompanyResponseForm
    form = form_class(request.POST, auto_id="note_%s" if internal else "response_%s")
    if form.is_valid():
        try:
            create_company_entry(user=request.user, company_id=request.company.pk,
                complaint_id=complaint.pk, body=form.cleaned_data["body"], internal=internal)
        except ValidationError as error:
            form.add_error(None, error.messages)
        else:
            messages.success(request, "Dahili not eklendi. Yalnızca şirket yetkilileriniz görebilir." if internal else "Şirket cevabınız kaydedildi.")
            return redirect("companies:complaint_detail", pk=complaint.pk)
    context = _detail_context(request, complaint, **{"note_form" if internal else "response_form": form})
    return render(request, "companies/panel/complaint_detail.html", context, status=400)


@company_panel_required
@require_POST
def response_create(request, pk):
    return _create_entry(request, pk, internal=False)


@company_panel_required
@require_POST
def note_create(request, pk):
    return _create_entry(request, pk, internal=True)


@company_panel_required
@require_safe
def responses(request):
    page = paginate(request, company_responses(request.company), "company_responses")
    return render(request, "companies/panel/responses.html", panel_context(request, "responses", page_obj=page))


@company_panel_required
@require_http_methods(["GET", "HEAD", "POST"])
def profile(request):
    if request.method == "POST":
        require_profile_role(request.company_membership)
        form = CompanyProfileForm(request.POST, request.FILES, instance=request.company)
        if form.is_valid():
            form.save()
            messages.success(request, "Şirket profiliniz güncellendi.")
            return redirect("companies:profile")
    else:
        form = CompanyProfileForm(instance=request.company)
    return render(request, "companies/panel/profile.html", panel_context(request, "profile", form=form),
        status=400 if request.method == "POST" else 200)


@company_panel_required
@require_safe
def members(request):
    require_profile_role(request.company_membership)
    roster = CompanyMembership.objects.filter(company=request.company).select_related("user").order_by("-created_at", "-pk")
    page = paginate(request, roster, "company_complaints")
    return render(request, "companies/panel/members.html", panel_context(request, "members", roster=page, page_obj=page))


@company_panel_required
@require_safe
def notifications(request):
    page = paginate(request, company_notifications(request.company, request.user), "company_notifications")
    return render(request, "companies/panel/notifications.html", panel_context(request, "notifications", page_obj=page))


@company_panel_required
@require_POST
def notification_read(request, pk):
    notification = get_object_or_404(company_notifications(request.company, request.user), pk=pk)
    CompanyNotificationRead.objects.get_or_create(notification=notification, user=request.user)
    return redirect("companies:notifications")


@company_panel_required
@require_safe
def notification_open(request, pk):
    notification = get_object_or_404(company_notifications(request.company, request.user), pk=pk)
    if notification.complaint_id:
        return redirect('companies:complaint_detail', pk=notification.complaint_id)
    return redirect('companies:profile')


@company_panel_required
@require_POST
def notifications_read_all(request):
    from itertools import batched
    ids = company_notifications(request.company, request.user).filter(is_read=False).values_list('pk', flat=True)
    # Batch inserts retain each member's independent read state.
    for batch in batched(ids.iterator(chunk_size=500), 500):
        CompanyNotificationRead.objects.bulk_create(
            [CompanyNotificationRead(notification_id=pk, user=request.user) for pk in batch],
            ignore_conflicts=True, batch_size=500)
    return redirect('companies:notifications')


@company_panel_required
@require_safe
def panel_settings(request):
    return render(request, "companies/panel/settings.html", panel_context(request, "settings"))
