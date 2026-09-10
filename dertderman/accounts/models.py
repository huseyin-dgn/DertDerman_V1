from django.contrib.auth.models import AbstractUser
from django.db import models
from uuid import uuid4


def user_profile_image_path(instance, filename):
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "img"
    return f"users/profile-images/{uuid4().hex}.{extension}"


class User(AbstractUser):
    class UserType(models.TextChoices):
        USER = "USER", "Kullanıcı"
        COMPANY = "COMPANY", "Şirket"
        ADMIN = "ADMIN", "Yönetici"

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)
    user_type = models.CharField(
        max_length=20,
        choices=UserType.choices,
        default=UserType.USER,
    )
    is_verified = models.BooleanField(default=False)
    profile_image = models.ImageField(
        upload_to=user_profile_image_path, blank=True, null=True
    )
    selected_avatar = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.username
