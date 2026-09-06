from django.contrib.auth import get_user_model
from django.shortcuts import render


def home(request):
    from companies.models import Company

    popular_companies = Company.objects.filter(is_active=True).order_by("name")[:6]
    context = {
        "stats": {
            "total_complaints": "—",
            "companies": Company.objects.filter(is_active=True).count(),
            "users": get_user_model().objects.count(),
            "solution_rate": "—",
        },
        "popular_companies": popular_companies,
    }
    return render(request, "home.html", context)
