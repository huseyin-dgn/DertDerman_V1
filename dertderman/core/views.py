from django.contrib.auth import get_user_model
from django.shortcuts import render
from django.db.models import Count, Q

from complaints.models import Complaint
from complaints.selectors import public_complaints
from blog.selectors import published_posts
from .presentation import HERO_BRAND_MESSAGES


def home(request):
    from companies.models import Company

    popular_companies = Company.objects.filter(is_active=True).select_related("category").order_by("name")[:6]
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

from django.shortcuts import render


def custom_404(request, exception=None, unmatched_path=None):
    return render(
        request,
        "404.html",
        status=404,
    )
