from .models import Post


def published_posts():
    return Post.objects.filter(status=Post.Status.PUBLISHED).order_by("-published_at", "-pk")
