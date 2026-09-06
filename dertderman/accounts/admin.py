from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "user_type",
        "is_verified",
        "is_staff",
        "is_active",
    )
    list_filter = ("user_type", "is_verified", "is_staff", "is_active")
    search_fields = ("username", "email", "first_name", "last_name", "phone")

    fieldsets = UserAdmin.fieldsets + (
        (
            "DertDerman Bilgileri",
            {
                "fields": (
                    "phone",
                    "user_type",
                    "is_verified",
                )
            },
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "DertDerman Bilgileri",
            {
                "fields": (
                    "email",
                    "phone",
                    "user_type",
                    "is_verified",
                )
            },
        ),
    )
