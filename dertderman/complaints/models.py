from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

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
