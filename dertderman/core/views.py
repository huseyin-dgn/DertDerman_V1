from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_safe
from django.views.decorators.cache import never_cache

from complaints.models import Complaint
from complaints.selectors import public_complaints
from blog.selectors import published_posts
from .presentation import HERO_BRAND_MESSAGES
from .forms import ContactRequestForm


def home(request):
    if settings.DEBUG and request.GET.get("intro") == "1":
        return redirect("/intro/?preview=1")

    from companies.models import Company

    from companies.selectors import public_companies
    popular_companies = public_companies().order_by("name", "pk")[:6]
    counts = Complaint.objects.aggregate(
        total_complaints=Count("pk"),
        published=Count("pk", filter=Q(status=Complaint.Status.PUBLISHED, company__is_active=True, withdrawn_at__isnull=True)),
        resolved=Count("pk", filter=Q(status=Complaint.Status.RESOLVED, withdrawn_at__isnull=True)),
    )
    context = {
        "hero_brand_messages": HERO_BRAND_MESSAGES,
        "stats": {
            **counts,
            "companies": Company.objects.count(),
            "users": get_user_model().objects.count(),
        },
        "popular_companies": popular_companies,
        "recent_complaints": public_complaints()[:4],
        "recent_posts": published_posts().defer("content")[:3],
    }
    return render(request, "home.html", context)


@require_safe
def about(request):
    return render(request, "core/about.html")

@require_safe
def privacy_policy(request):
    return render(
        request,
        "core/legal/privacy.html",
    )


@require_http_methods(["GET", "HEAD", "POST"])
def contact(request):
    submitted = request.GET.get("sent") == "1"
    form = ContactRequestForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect(f"{reverse('core:contact')}?sent=1")
    return render(request, "core/contact.html", {
        "form": form,
        "submitted": submitted,
        "support_email": getattr(settings, "SUPPORT_EMAIL", "").strip(),
    }, status=400 if request.method == "POST" else 200)


@never_cache
def intro(request):
    preview = request.GET.get("preview") == "1"
    return render(request, "intro.html", {
        "intro_preview": preview,
        "intro_debug_motion": settings.DEBUG,
        "intro_full_motion": settings.DEBUG or preview,
    })


@never_cache
def intro_reset(request):
    if not settings.DEBUG:
        raise Http404
    return redirect("core:intro")


def custom_404(request, exception=None, unmatched_path=None):
    return render(
        request,
        "404.html",
        status=404,
    )

def custom_500(request):
    return render(
        request,
        "500.html",
        status=500,
    )

def custom_400(request, exception=None):
    return render(
        request,
        "400.html",
        status=400,
    )

@require_safe
def disclosure_notice(request):
    return render(
        request,
        "core/legal/disclosure.html",
    )