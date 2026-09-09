from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache

from complaints.models import Complaint
from complaints.selectors import public_complaints
from blog.selectors import published_posts
from .presentation import HERO_BRAND_MESSAGES


def home(request):
    if settings.DEBUG and request.GET.get("intro") == "1":
        return redirect("/intro/?preview=1")

    from companies.models import Company

    from companies.selectors import public_companies
    popular_companies = public_companies().order_by("name", "pk")[:6]
    counts = Complaint.objects.aggregate(
        total_complaints=Count("pk"),
        published=Count("pk", filter=Q(status=Complaint.Status.PUBLISHED, company__is_active=True)),
        resolved=Count("pk", filter=Q(status=Complaint.Status.RESOLVED)),
    )
    context = {
        "hero_brand_messages": HERO_BRAND_MESSAGES,
        "stats": {
            **counts,
            "companies": Company.objects.count(),
            "users": get_user_model().objects.count(),
        },
        "popular_companies": popular_companies,
        "recent_complaints": public_complaints()[:6],
        "recent_posts": published_posts().defer("content")[:3],
    }
    return render(request, "home.html", context)


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
