from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import Company, CompanyMembership


def active_company_memberships_for(user):
    if not user.is_authenticated:
        return CompanyMembership.objects.none()

    return (
        CompanyMembership.objects.filter(
            user=user,
            is_active=True,
            company__is_active=True,
            company__approval_status=Company.ApprovalStatus.APPROVED,
        )
        .select_related("company", "company__category")
        .order_by("company__name")
    )


def get_accessible_company_membership(user, slug):
    membership = active_company_memberships_for(user).filter(company__slug=slug).first()
    if membership is None:
        raise PermissionDenied
    return membership


@transaction.atomic
def decide_company_application(company_id, target_status):
    if target_status not in {
        Company.ApprovalStatus.APPROVED,
        Company.ApprovalStatus.REJECTED,
    }:
        raise ValueError("Geçersiz şirket başvurusu kararı.")

    company = Company.objects.select_for_update().get(pk=company_id)
    if company.approval_status != Company.ApprovalStatus.PENDING:
        return company, False

    memberships = CompanyMembership.objects.select_for_update().filter(company=company)
    if target_status == Company.ApprovalStatus.APPROVED:
        owner_membership = memberships.filter(
            role=CompanyMembership.Role.OWNER,
            user__user_type="COMPANY",
        ).order_by("pk").first()
        if owner_membership is None:
            raise ValidationError("Başvuruya bağlı geçerli şirket yetkilisi bulunamadı.")
        memberships.exclude(pk=owner_membership.pk).update(is_active=False)
        if not owner_membership.is_active:
            owner_membership.is_active = True
            owner_membership.save(update_fields=["is_active"])
        company.is_active = True
    else:
        memberships.update(is_active=False)
        company.is_active = False

    company.approval_status = target_status
    company.save(update_fields=["approval_status", "is_active", "updated_at"])
    return company, True
