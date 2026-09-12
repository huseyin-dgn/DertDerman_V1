from core.pagination import paginate
from core.view_tracking import record_unique_session_view
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_safe
from django.views.decorators.vary import vary_on_headers

from .selectors import published_posts


@require_safe
def post_list(request):
    search = request.GET.get(
        "s",
        request.GET.get("q", "")
    ).strip()[:180]

    posts = published_posts().defer("content")

    if search:
        posts = posts.filter(
            Q(title__icontains=search)
            | Q(excerpt__icontains=search)
        )

    page_obj = paginate(
        request,
        posts,
        "public_blog",
    )

    return render(
        request,
        "blog/post_list.html",
        {
            "page_obj": page_obj,
            "search": search,
        },
    )


@require_safe
@vary_on_headers("X-Article-Reader")
def post_detail(request, slug):
    post = get_object_or_404(
        published_posts(),
        slug=slug,
    )

    post.view_count = record_unique_session_view(
        request,
        instance=post,
        namespace="blog_post",
    )

    template = (
        "blog/article.html"
        if request.headers.get(
            "X-Article-Reader"
        ) == "1"
        else "blog/post_detail.html"
    )

    response = render(
        request,
        template,
        {
            "post": post,
        },
    )

    response["Cache-Control"] = "no-cache"

    return response
