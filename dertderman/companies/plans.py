from django.db.models import Q
from django.utils import timezone

from .models import CompanySubscription


def active_pro_subscriptions():
    """
    Gerçekten Pro hakkı veren subscription queryset'i.

    is_active=True olmalı ve:
    - bitiş tarihi yoksa devam eder,
    - veya bitiş tarihi gelecekte olmalıdır.
    """
    now = timezone.now()

    return (
        CompanySubscription.objects
        .filter(
            plan=CompanySubscription.Plan.PRO,
            is_active=True,
        )
        .filter(
            Q(current_period_end__isnull=True)
            | Q(current_period_end__gt=now)
        )
    )


def company_has_active_pro(company):
    """
    Şirketin aktif DertDerman Pro hakkı var mı?

    Subscription kaydı yoksa Standart Firma kabul edilir.
    """
    company_id = getattr(company, "pk", None)

    if not company_id:
        return False

    return active_pro_subscriptions().filter(
        company_id=company_id,
    ).exists()


def company_plan_code(company):
    return (
        "PRO"
        if company_has_active_pro(company)
        else "STANDARD"
    )
