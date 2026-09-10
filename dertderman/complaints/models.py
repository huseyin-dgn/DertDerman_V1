from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from companies.models import Company


class Complaint(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "İncelemede"
        PUBLISHED = "PUBLISHED", "Yayında"
        RESOLVED = "RESOLVED", "Çözüldü"
        REJECTED = "REJECTED", "Reddedildi"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="complaints",
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="complaints",
    )
    title = models.CharField(max_length=150)
    description = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ("-created_at",)

    def clean(self):
        errors = {}
        title = self.title.strip() if self.title else ""
        description = self.description.strip() if self.description else ""

        if len(title) < 5:
            errors["title"] = "Başlık en az 5 karakter olmalıdır."
        if len(description) < 20:
            errors["description"] = "Açıklama en az 20 karakter olmalıdır."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title


class ComplaintEvent(models.Model):
    class Type(models.TextChoices):
        CREATED = "CREATED", "Şikayet oluşturuldu"
        PENDING = "PENDING", "İncelemeye alındı"
        PUBLISHED = "PUBLISHED", "Yayınlandı"
        COMPANY_RESPONDED = "COMPANY_RESPONDED", "Şirket cevapladı"
        RESOLVED = "RESOLVED", "Çözüldü"
        REJECTED = "REJECTED", "Reddedildi"
        EDITED = "EDITED", "Kullanıcı tarafından düzenlendi"
        WITHDRAWN = "WITHDRAWN", "Geri çekildi"

    class Actor(models.TextChoices):
        SYSTEM = "SYSTEM", "Sistem"
        USER = "USER", "Kullanıcı"
        ADMIN = "ADMIN", "Yönetici"
        COMPANY = "COMPANY", "Şirket"

    complaint = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="timeline_events"
    )
    event_type = models.CharField(max_length=24, choices=Type.choices)
    actor_type = models.CharField(
        max_length=12, choices=Actor.choices, default=Actor.SYSTEM
    )
    message = models.CharField(max_length=300)
    source_key = models.CharField(max_length=180, unique=True)
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("occurred_at", "pk")
        indexes = [
            models.Index(
                fields=("complaint", "occurred_at"), name="complaint_timeline"
            )
        ]

    def __str__(self):
        return f"{self.complaint_id}: {self.event_type}"


class ComplaintLike(models.Model):
    complaint = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="likes"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="complaint_likes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("complaint", "user"), name="unique_complaint_like"
            )
        ]
        ordering = ("-created_at", "-pk")


class ComplaintReaction(models.Model):
    class Type:
        # Compatibility names for callers; values are now the actual emoji.
        AGREE = "👍"
        SUPPORT = "❤️"
        SURPRISED = "😮"
        SAD = "😕"

    complaint = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="reactions"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="complaint_reactions",
    )
    reaction_type = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("complaint", "user"), name="unique_complaint_reaction"
            )
        ]
        ordering = ("-updated_at", "-pk")


class ComplaintComment(models.Model):
    complaint = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="comments"
    )
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="complaint_comments",
    )
    body = models.TextField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(
                fields=("complaint", "is_active", "-created_at"),
                name="complaint_comment_recent",
            )
        ]

    def clean(self):
        super().clean()
        self.body = (self.body or "").strip()
        if not self.body:
            raise ValidationError({"body": "Yorum boş bırakılamaz."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
