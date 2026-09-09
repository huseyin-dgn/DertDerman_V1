"""Destructive UI actions preserve the records and their existing relations."""
import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from blog.models import Post
from companies.models import Company, CompanyNotification

logger = logging.getLogger(__name__)


@transaction.atomic
def archive_post(*, pk, actor):
    post = get_object_or_404(Post.objects.select_for_update(), pk=pk)
    changed = Post.objects.filter(pk=post.pk).exclude(status=Post.Status.ARCHIVED).update(
        status=Post.Status.ARCHIVED, updated_at=timezone.now())
    if changed:
        transaction.on_commit(lambda: logger.info("Blog archived: post_id=%s actor_id=%s", post.pk, actor.pk))
    return bool(changed)


@transaction.atomic
def archive_company(*, pk, actor):
    # Share the approval row lock so a pending application cannot be revived.
    company = get_object_or_404(Company.objects.select_for_update(), pk=pk)
    if company.archived_at is not None:
        return False
    now = timezone.now()
    Company.objects.filter(pk=company.pk).update(is_active=False, archived_at=now, updated_at=now)
    CompanyNotification.objects.create(company=company, kind=CompanyNotification.Kind.ADMIN, title="Şirket arşivlendi.")
    transaction.on_commit(lambda: logger.info("Company archived: company_id=%s actor_id=%s", company.pk, actor.pk))
    return True
