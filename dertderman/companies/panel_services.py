from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import get_object_or_404

from complaints.models import Complaint
from .complaint_policy import company_can_interact_with_complaint
from .models import Company, CompanyMembership, CompanyResponse, InternalCompanyNote
from .panel_forms import CompanyProfileForm
from .panel_permissions import require_company_membership, require_profile_role
from .plans import company_has_active_pro


@transaction.atomic
def create_company_entry(*, user, company_id, complaint_id, body, internal=False):
    # Recheck access here too: callers cannot supply company/author via form data.
    membership = require_company_membership(user, company_id)
    complaint = get_object_or_404(
        Complaint.objects.select_for_update().filter(company_id=membership.company_id), pk=complaint_id,
    )
    model = InternalCompanyNote if internal else CompanyResponse

    # Sikayet yasam dongusu servis seviyesinde de
    # kontrol edilir. UI veya view atlatilsa bile
    # kapali bir kayda yeni icerik yazilamaz.
    if not company_can_interact_with_complaint(
        complaint
    ):
        raise ValidationError(
            "Bu sikayet sirket etkilesimine "
            "acik degil."
        )

    # Kurumsal yanit ve dahili not DertDerman Pro haklaridir.
    # UI atlatilsa bile servis katmaninda tekrar kontrol edilir.
    if not company_has_active_pro(membership.company):
        feature = (
            "Dahili not ekleyebilmek"
            if internal
            else "Sikayetlere kurumsal yanit verebilmek"
        )

        raise ValidationError(
            f"{feature} icin "
            "DertDerman Pro paketine gecmeniz gerekir."
        )

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


def _locked_profile_membership(*, user, company_id):
    if (
        not user.is_authenticated
        or not user.is_active
        or user.user_type != "COMPANY"
    ):
        raise PermissionDenied

    company = (
        Company.objects.select_for_update()
        .filter(pk=company_id)
        .first()
    )
    if (
        company is None
        or not company.is_active
        or company.archived_at is not None
        or not company.is_verified
        or company.approval_status != Company.ApprovalStatus.APPROVED
    ):
        raise PermissionDenied

    membership = (
        CompanyMembership.objects.select_for_update()
        .filter(
            user=user,
            company=company,
            is_active=True,
            role__in=CompanyMembership.Role.values,
        )
        .first()
    )
    if membership is None:
        raise PermissionDenied

    require_profile_role(membership)
    return company, membership


@transaction.atomic
def update_company_profile(*, user, company_id, data, files):
    """Validate and update the currently authorized company under a row lock."""
    company, _membership = _locked_profile_membership(
        user=user,
        company_id=company_id,
    )
    form = CompanyProfileForm(data, files, instance=company)
    if not form.is_valid():
        return company, form, False

    company = form.save()
    return company, form, True


@transaction.atomic
def remove_company_logo(*, user, company_id):
    company, _membership = _locked_profile_membership(
        user=user,
        company_id=company_id,
    )
    if company.logo:
        raise ValidationError(CompanyProfileForm.LOCKED_IDENTITY_ERROR)
    return company, False
