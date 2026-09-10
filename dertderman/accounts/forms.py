from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError
from django.forms import ModelForm
from django import forms

from .models import User
from .avatars import USER_AVATAR_CHOICES


USER_LOGIN_ERROR = "Giriş bilgileriniz doğrulanamadı. Kullanıcı adınızı ve şifrenizi kontrol edin."


class UserAuthenticationForm(AuthenticationForm):
    error_messages = {"invalid_login": USER_LOGIN_ERROR, "inactive": USER_LOGIN_ERROR}

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.user_type != User.UserType.USER:
            raise ValidationError(USER_LOGIN_ERROR, code="invalid_login")


class RegisterForm(UserCreationForm):
    selected_avatar = forms.ChoiceField(
        label="Avatar", choices=USER_AVATAR_CHOICES, required=True, widget=forms.RadioSelect,
    )
    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "selected_avatar",
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
    selected_avatar = forms.ChoiceField(
        label="Hazır avatar", choices=USER_AVATAR_CHOICES, required=False,
        widget=forms.RadioSelect,
    )
    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "email",
            "phone",
            "selected_avatar",
        )
