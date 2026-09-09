"""Server-side list sizes shared by every workspace."""
from django.core.paginator import Paginator

PAGE_SIZES = {
    "admin": 5, "public_companies": 8, "public_complaints": 8,
    "public_blog": 6, "user_complaints": 6, "user_notifications": 8,
    "company_complaints": 6, "company_responses": 6,
    "company_notifications": 8, "admin_notifications": 10, "activity": 10,
}
PREVIEW_SIZE = 5


def paginate(request, queryset, kind, *, page_param="page"):
    # Callers supply an explicit, stable ordering (including the primary key).
    return Paginator(queryset, PAGE_SIZES[kind]).get_page(request.GET.get(page_param))
