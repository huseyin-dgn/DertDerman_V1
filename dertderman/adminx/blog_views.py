from django.contrib import messages
from .filters import BlogFilters, list_context
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from blog.forms import PostForm
from blog.models import Post
from .decorators import admin_required
from .services import archive_post


@admin_required
@require_safe
def post_list(request):
    posts = Post.objects.select_related("author").only(
        "title", "status", "created_at", "published_at", "author__username", "author__first_name", "author__last_name")
    if not request.GET.get("status"):
        posts = posts.exclude(status=Post.Status.ARCHIVED)
    context = list_context(request, posts, BlogFilters,
        search_fields=("title", "excerpt"), fields={"status": "status"})
    return render(request, "adminx/blog_list.html", context)


@admin_required
@require_http_methods(["GET", "HEAD", "POST"])
def post_create(request):
    form = PostForm(request.POST if request.method == "POST" else None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        post = form.save(commit=False)
        post.status = Post.Status.DRAFT
        post.author = request.user
        post.published_at = None
        post.save()
        messages.success(request, "Blog yazısı taslak olarak kaydedildi.")
        return redirect("adminx:blog_edit", pk=post.pk)
    return render(request, "adminx/blog_form.html", {"form": form})


@admin_required
@require_http_methods(["GET", "HEAD", "POST"])
def post_edit(request, pk):
    post = get_object_or_404(Post.objects.exclude(status=Post.Status.ARCHIVED), pk=pk)
    form = PostForm(request.POST if request.method == "POST" else None, request.FILES or None, instance=post)
    if request.method == "POST" and form.is_valid():
        post = form.save(commit=False)
        # Save the allowlist only: an edit must not overwrite a concurrent publish.
        post.save(update_fields=["title", "excerpt", "content", "cover_image", "updated_at"])
        messages.success(request, "Blog yazısı güncellendi.")
        return redirect("adminx:blog_edit", pk=post.pk)
    return render(request, "adminx/blog_form.html", {"form": form, "post": post})


@admin_required
@require_POST
def post_publish(request, pk):
    post = get_object_or_404(Post.objects.exclude(status=Post.Status.ARCHIVED), pk=pk)
    now = timezone.now()
    changed = Post.objects.filter(pk=pk, status=Post.Status.DRAFT).update(
        status=Post.Status.PUBLISHED, published_at=now, updated_at=now,
    )
    if not changed:
        return render(request, "adminx/blog_form.html", {
            "post": post, "form": PostForm(instance=post),
            "publish_error": "Bu yazı zaten yayınlanmış. İşlem tekrarlanmadı.",
        }, status=409)
    messages.success(request, "Blog yazısı yayınlandı.")
    return redirect("adminx:blog_edit", pk=pk)


@admin_required
@require_POST
def post_delete(request, pk):
    changed = archive_post(pk=pk, actor=request.user)
    if changed:
        messages.success(request, "Blog yazısı silindi.")
    else:
        messages.info(request, "Bu blog yazısı daha önce silinmiş.")
    return redirect("adminx:blog_list")
