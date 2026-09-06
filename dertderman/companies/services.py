from django.core.exceptions import PermissionDenied

from .models import CompanyMembership


def active_company_memberships_for(user):
    if not user.is_authenticated:
        return CompanyMembership.objects.none()

    return (
        CompanyMembership.objects.filter(
            user=user,
            is_active=True,
            company__is_active=True,
        )
        .select_related("company", "company__category")
        .order_by("company__name")
    )


def get_accessible_company_membership(user, slug):
    membership = active_company_memberships_for(user).filter(company__slug=slug).first()
    if membership is None:
        raise PermissionDenied
    return membership
