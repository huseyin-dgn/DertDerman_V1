from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Company, CompanyCategory, CompanyMembership


def active_company_memberships_for(user):
    if (
        not user.is_authenticated
        or not user.is_active
        or user.user_type != "COMPANY"
    ):
        return CompanyMembership.objects.none()

    return (
        CompanyMembership.objects.filter(
            user=user,
            is_active=True,
            role__in=CompanyMembership.Role.values,
            company__is_active=True,
            company__archived_at__isnull=True,
            company__is_verified=True,
            company__approval_status=Company.ApprovalStatus.APPROVED,
        )
        .select_related(
            "company",
            "company__category",
        )
        .order_by("company__name")
    )


def get_accessible_company_membership(user, slug):
    membership = (
        active_company_memberships_for(user)
        .filter(company__slug=slug)
        .first()
    )

    if membership is None:
        raise PermissionDenied

    return membership


@transaction.atomic
def decide_company_application(
    company_id,
    target_status,
    *,
    actor=None,
    rejection_reason="",
):
    if target_status not in {
        Company.ApprovalStatus.APPROVED,
        Company.ApprovalStatus.REJECTED,
    }:
        raise ValueError(
            "Geçersiz şirket başvurusu kararı."
        )

    company = Company.objects.select_for_update().get(
        pk=company_id
    )

    if company.archived_at is not None:
        raise ValidationError(
            "Arşivlenmiş şirket başvurusu sonuçlandırılamaz."
        )

    if company.approval_status != Company.ApprovalStatus.PENDING:
        return company, False

    rejection_reason = (rejection_reason or "").strip()

    if target_status == Company.ApprovalStatus.REJECTED:
        if not (
            actor is not None
            and getattr(actor, "is_authenticated", False)
            and actor.is_active
            and actor.user_type == "ADMIN"
        ):
            raise ValidationError(
                "Şirket başvurusu kararı için geçerli yönetici gereklidir."
            )

        if not rejection_reason:
            raise ValidationError(
                "Şirket başvurusu reddedilirken neden belirtilmelidir."
            )

        if len(rejection_reason) > 1000:
            raise ValidationError(
                "Şirket başvurusu red nedeni 1000 karakteri aşamaz."
            )

    memberships = (
        CompanyMembership.objects
        .select_for_update()
        .filter(company=company)
    )

    if target_status == Company.ApprovalStatus.APPROVED:
        owner_membership = (
            memberships.filter(
                role=CompanyMembership.Role.OWNER,
                user__user_type="COMPANY",
            )
            .order_by("pk")
            .first()
        )

        if owner_membership is None:
            raise ValidationError(
                "Başvuruya bağlı geçerli şirket yetkilisi bulunamadı."
            )

        memberships.exclude(
            pk=owner_membership.pk
        ).update(
            is_active=False
        )

        if not owner_membership.is_active:
            owner_membership.is_active = True
            owner_membership.save(
                update_fields=["is_active"]
            )

        if not owner_membership.user.is_active:
            owner_membership.user.is_active = True
            owner_membership.user.save(
                update_fields=["is_active"]
            )

        company.is_active = True
        company.is_verified = True

    else:
        memberships.update(
            is_active=False
        )

        company.is_active = False
        company.is_verified = False
        company.rejection_reason = rejection_reason
        company.rejected_at = timezone.now()

    company.approval_status = target_status

    company.save(
        update_fields=[
            "approval_status",
            "is_active",
            "is_verified",
            "rejection_reason",
            "rejected_at",
            "updated_at",
        ]
    )

    if target_status == Company.ApprovalStatus.REJECTED:
        from adminx.models import AdminAuditLog

        AdminAuditLog.objects.create(
            actor=actor,
            action=AdminAuditLog.Action.REJECT,
            target_type="company_application",
            target_id=str(company.pk),
            target_label=company.name,
            description="Şirket başvurusu reddedildi.",
            metadata={
                "previous_status": Company.ApprovalStatus.PENDING,
                "new_status": Company.ApprovalStatus.REJECTED,
                "rejection_reason": rejection_reason,
            },
        )

    return company, True


@transaction.atomic
def resubmit_company_application(
    *,
    user,
    company_id,
    company_name,
    category,
    phone,
    website,
):
    """
    Reddedilmis basvuruyu yeni bir hesap olusturmadan
    tekrar PENDING durumuna getirir.

    Kullanici sifre dogrulamasi view/form katmaninda,
    kritik durum kontrolleri burada tekrar yapilir.
    """

    company = (
        Company.objects
        .select_for_update()
        .get(
            pk=company_id
        )
    )

    membership = (
        CompanyMembership.objects
        .select_for_update()
        .filter(
            company=company,
            user=user,
            role=CompanyMembership.Role.OWNER,
        )
        .first()
    )

    if (
        membership is None
        or user.user_type != "COMPANY"
    ):
        raise ValidationError(
            "Geçerli şirket yetkilisi bulunamadı."
        )

    if company.archived_at is not None:
        raise ValidationError(
            "Arşivlenmiş şirket yeniden başvuru yapamaz."
        )

    if (
        company.approval_status
        != Company.ApprovalStatus.REJECTED
    ):
        raise ValidationError(
            "Yalnızca reddedilmiş başvurular "
            "yeniden incelemeye gönderilebilir."
        )

    if not CompanyCategory.objects.filter(
        pk=category.pk,
        is_active=True,
    ).exists():
        raise ValidationError(
            "Geçerli bir şirket kategorisi seçin."
        )

    now = timezone.now()

    # QuerySet.update kullanarak bu kullanıcı işleminin
    # admin kararı sinyali gibi yorumlanmasını engelliyoruz.
    Company.objects.filter(
        pk=company.pk
    ).update(
        name=company_name.strip(),
        email=user.email,
        phone=phone.strip(),
        website=(website or "").strip(),
        category=category,
        approval_status=(
            Company.ApprovalStatus.PENDING
        ),
        is_active=False,
        is_verified=False,
        updated_at=now,
    )

    # Admin tekrar onaylayana kadar panel kapalı kalır.
    if membership.is_active:
        membership.is_active = False
        membership.save(
            update_fields=[
                "is_active"
            ]
        )

    if (
        getattr(user, "phone", "")
        != phone.strip()
    ):
        user.phone = phone.strip()
        user.save(
            update_fields=[
                "phone"
            ]
        )

    company.refresh_from_db()

    from notifications.services import send_admins

    reapplication_cycle = (
        company.rejected_at.isoformat()
        if company.rejected_at
        else now.isoformat()
    )
    send_admins(
        kind="APPLICATION",
        event_key=(
            f"company:{company.pk}:reapplication:"
            f"{reapplication_cycle}"
        ),
        title="Şirket başvurusu yeniden inceleme bekliyor.",
        message=company.name,
        company=company,
    )

    return company
