from django.shortcuts import redirect, render
from django.views.decorators.http import require_safe

from companies.panel_permissions import (
    company_panel_required,
    require_profile_role,
)
from companies.panel_views import panel_context
from companies.plans import company_has_active_pro


PAYMENT_PREVIEW_OPTIONS = {
    "monthly": {
        "label": "Aylık",
        "price": "49,90",
        "suffix": "/ ay",
        "description": "Aylık kullanım için DertDerman Pro.",
    },
    "yearly": {
        "label": "Yıllık",
        "price": "499,90",
        "suffix": "/ yıl",
        "description": "Yıllık ödeme ile 2 ay ücretsiz.",
    },
}


@company_panel_required
@require_safe
def checkout_preview(request):
    """
    Provider-neutral Pro ödeme önizleme ekranı.

    Bu aşama ödeme başlatmaz, kart verisi toplamaz ve
    CompanySubscription üzerinde hiçbir değişiklik yapmaz.
    Gerçek provider entegrasyonu geldiğinde ödeme başlatma
    endpoint'i ayrı bir POST akışı olarak eklenecektir.
    """
    require_profile_role(request.company_membership)

    if company_has_active_pro(request.company):
        return redirect("companies:plan")

    selected_billing = (
        request.GET.get("period", "monthly")
        .strip()
        .lower()
    )

    if selected_billing not in PAYMENT_PREVIEW_OPTIONS:
        selected_billing = "monthly"

    option = PAYMENT_PREVIEW_OPTIONS[selected_billing]

    return render(
        request,
        "payments/payment.html",
        panel_context(
            request,
            "plan",
            selected_billing=selected_billing,
            payment_option=option,
        ),
    )
