import logging
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from blog.models import Post
from accounts.models import User
from companies.models import Company, CompanyNotification

from .models import AdminAuditLog


logger = logging.getLogger(__name__)


def _require_current_admin(actor):
    if not (
        actor is not None
        and getattr(actor, "is_authenticated", False)
        and getattr(actor, "pk", None)
        and User.objects.filter(
            pk=actor.pk,
            is_active=True,
            is_permanently_closed=False,
            user_type=User.UserType.ADMIN,
        ).exists()
    ):
        raise ValidationError("Bu yönetim işlemi için geçerli yönetici gereklidir.")


def _get_client_ip(request):
    if request is None:
        return None

    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR")


def record_admin_audit(
    *,
    actor,
    action,
    target_type,
    target_id="",
    target_label="",
    description="",
    metadata=None,
    request=None,
):
    return AdminAuditLog.objects.create(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else "",
        target_label=target_label or "",
        description=description or "",
        metadata=metadata or {},
        ip_address=_get_client_ip(request),
    )


@transaction.atomic
def archive_post(*, pk, actor):
    post = get_object_or_404(
        Post.objects.select_for_update(),
        pk=pk,
    )

    changed = (
        Post.objects
        .filter(pk=post.pk)
        .exclude(status=Post.Status.ARCHIVED)
        .update(
            status=Post.Status.ARCHIVED,
            updated_at=timezone.now(),
        )
    )

    if changed:
        transaction.on_commit(
            lambda: logger.info(
                "Blog archived: post_id=%s actor_id=%s",
                post.pk,
                actor.pk,
            )
        )

    return bool(changed)


@transaction.atomic
def archive_company(*, pk, actor):
    _require_current_admin(actor)

    company = get_object_or_404(
        Company.objects.select_for_update(),
        pk=pk,
    )

    if company.archived_at is not None:
        return False

    now = timezone.now()

    Company.objects.filter(pk=company.pk).update(
        is_active=False,
        archived_at=now,
        updated_at=now,
    )

    CompanyNotification.objects.create(
        company=company,
        kind=CompanyNotification.Kind.ADMIN,
        title="Şirket arşivlendi.",
    )

    AdminAuditLog.objects.create(
        actor=actor,
        action=AdminAuditLog.Action.ARCHIVE,
        target_type="company",
        target_id=str(company.pk),
        target_label=company.name,
        description="Şirket arşivlendi.",
        metadata={
            "previous_is_active": company.is_active,
            "archived_at": now.isoformat(),
        },
    )

    transaction.on_commit(
        lambda: logger.info(
            "Company archived: company_id=%s actor_id=%s",
            company.pk,
            actor.pk,
        )
    )

    return True
