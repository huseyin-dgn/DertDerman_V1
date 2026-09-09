from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from core.pagination import paginate
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_safe

from accounts.models import User
from core.decorators import role_required

from .forms import ComplaintCreateForm
from .models import Complaint
from .selectors import public_complaints


@require_safe
def public_complaint_list(request):
    page_obj = paginate(request, public_complaints(), "public_complaints")
    return render(request, "complaints/public_list.html", {"page_obj": page_obj})


@require_safe
def public_complaint_detail(request, pk):
    complaint = get_object_or_404(public_complaints(), pk=pk)
    from companies.panel_selectors import company_responses
    responses = company_responses(complaint.company).filter(complaint=complaint)
    return render(request, "complaints/public_detail.html", {
        "complaint": complaint,
        "company_response_page": paginate(request, responses, "company_responses", page_param="response_page"),
    })


@role_required(User.UserType.USER)
@require_safe
def complaint_list(request):
    complaints = (
        Complaint.objects.filter(user=request.user)
        .select_related("company")
        .order_by("-created_at", "-pk")
    )
    page = paginate(request, complaints, "user_complaints")
    return render(request, "complaints/complaint_list.html", {"complaints": page, "page_obj": page})


@role_required(User.UserType.USER)
@require_safe
def complaint_detail(request, pk):
    complaint = get_object_or_404(
        Complaint.objects.select_related("company"), pk=pk, user=request.user
    )
    from companies.panel_selectors import company_responses
    return render(request, "complaints/complaint_detail.html", {"complaint": complaint,
        'company_response_page': paginate(request, company_responses(complaint.company).filter(complaint=complaint),
                                         'company_responses', page_param='response_page')})


@role_required(User.UserType.USER)
@transaction.atomic
def complaint_create(request):
    if request.method == "POST":
        form = ComplaintCreateForm(request.POST)
        if form.is_valid():
            # Serialize this user's submissions and absorb rapid identical retries.
            User.objects.select_for_update().get(pk=request.user.pk)
            existing = Complaint.objects.filter(user=request.user, company=form.cleaned_data['company'],
                title=form.cleaned_data['title'], description=form.cleaned_data['description'],
                created_at__gte=timezone.now() - timedelta(seconds=30)).first()
            if existing:
                return redirect('dashboard:home')
            complaint = form.save(commit=False)
            complaint.user = request.user
            complaint.status = Complaint.Status.PENDING
            complaint.save()
            messages.success(
                request,
                "Şikayetiniz incelemeye alındı. Yayınlanmadan önce değerlendirilecektir.",
            )
            return redirect("dashboard:home")
    else:
        form = ComplaintCreateForm()

    return render(request, "complaints/complaint_create.html", {"form": form})
