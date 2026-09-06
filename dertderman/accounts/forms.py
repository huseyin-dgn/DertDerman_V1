from django.contrib.auth.forms import UserCreationForm
from django.forms import ModelForm

from .models import User


class RegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "password1",
            "password2",
        )

    def save(self, commit=True):
        user = super().save(commit=False)
        user.user_type = User.UserType.USER
        user.is_staff = False
        user.is_superuser = False
        user.is_verified = False
        if commit:
            user.save()
        return user


class ProfileUpdateForm(ModelForm):
    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "email",
            "phone",
        )
