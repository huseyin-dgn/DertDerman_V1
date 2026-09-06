from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_safe

from .selectors import published_posts


@require_safe
def post_list(request):
    page_obj = Paginator(published_posts().defer("content"), 9).get_page(request.GET.get("page"))
    return render(request, "blog/post_list.html", {"page_obj": page_obj})


@require_safe
def post_detail(request, slug):
    post = get_object_or_404(published_posts(), slug=slug)
    return render(request, "blog/post_detail.html", {"post": post})
