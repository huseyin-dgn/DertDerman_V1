from uuid import uuid4

from django.db import models
from django.conf import settings
from django.utils.text import slugify


def cover_upload_path(instance, filename):
    # The upload form re-encodes all accepted images as WebP.
    return f"blog/covers/{uuid4().hex}.webp"


class Post(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Taslak"
        PUBLISHED = "PUBLISHED", "Yayında"
        ARCHIVED = "ARCHIVED", "Silindi / Arşivlendi"

    title = models.CharField("Başlık", max_length=180)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="blog_posts", editable=False)
    slug = models.SlugField(max_length=220, unique=True, editable=False)
    excerpt = models.CharField("Kısa açıklama", max_length=320)
    content = models.TextField("İçerik")
    cover_image = models.ImageField("Kapak görseli", upload_to=cover_upload_path, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [models.Index(fields=["status", "-published_at"], name="blog_publication_idx")]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = f"{slugify(self.title)[:160] or 'yazi'}-{uuid4().hex}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
