from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify


def generate_unique_slug(instance, value):
    model = instance.__class__
    slug_field = model._meta.get_field("slug")
    base_slug = slugify(value) or model._meta.model_name
    base_slug = base_slug[: slug_field.max_length]
    slug = base_slug
    queryset = model._default_manager.all()

    if instance.pk:
        queryset = queryset.exclude(pk=instance.pk)

    counter = 2
    while queryset.filter(slug=slug).exists():
        suffix = f"-{counter}"
        slug = f"{base_slug[: slug_field.max_length - len(suffix)]}{suffix}"
        counter += 1

    return slug


def company_logo_upload_path(instance, filename):
    extension = Path(filename).suffix.lower()
    safe_slug = instance.slug or slugify(instance.name) or "company"
    return f"companies/logos/{safe_slug}{extension}"


class CompanyCategory(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "company category"
        verbose_name_plural = "company categories"

    def save(self, *args, **kwargs):
        self.slug = generate_unique_slug(self, self.slug or self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Company(models.Model):
    class ApprovalStatus(models.TextChoices):
        PENDING = "PENDING", "Onay bekliyor"
        APPROVED = "APPROVED", "Onaylandı"
        REJECTED = "REJECTED", "Reddedildi"

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True, blank=True)
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    logo = models.ImageField(
        upload_to=company_logo_upload_path,
        blank=True,
        null=True,
    )
    category = models.ForeignKey(
        CompanyCategory,
        on_delete=models.SET_NULL,
        related_name="companies",
        blank=True,
        null=True,
    )
    is_verified = models.BooleanField(default=False)
    approval_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.APPROVED,
        db_index=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def save(self, *args, **kwargs):
        self.slug = generate_unique_slug(self, self.slug or self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class CompanyMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Yetkili"
        MANAGER = "MANAGER", "Yönetici"
        SUPPORT = "SUPPORT", "Destek"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="company_memberships",
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.SUPPORT,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "company"),
                name="unique_company_membership_per_user",
            ),
        ]
        ordering = ("company__name", "user__username")

    def clean(self):
        if self.user_id and self.user.user_type != "COMPANY":
            raise ValidationError(
                {"user": "Company membership sadece COMPANY kullanıcılar içindir."}
            )

    def __str__(self):
        return f"{self.user} - {self.company} ({self.role})"
