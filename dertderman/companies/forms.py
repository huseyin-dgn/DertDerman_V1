import uuid

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.models import User

from .models import Company, CompanyMembership
from .services import active_company_memberships_for


COMPANY_LOGIN_ERROR = "Kurumsal giriş bilgileri doğrulanamadı."


class CompanyRegistrationForm(UserCreationForm):
    company_name = forms.CharField(label="Şirket adı", max_length=255)
    first_name = forms.CharField(label="Yetkili adı", max_length=150)
    last_name = forms.CharField(label="Yetkili soyadı", max_length=150)
    email = forms.EmailField(
        label="Kurumsal e-posta",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    phone = forms.CharField(label="Telefon", max_length=20)
    website = forms.URLField(label="Web sitesi", required=False)

    field_order = (
        "company_name",
        "first_name",
        "last_name",
        "email",
        "phone",
        "website",
        "password1",
        "password2",
    )

    class Meta:
        model = User
        fields = (
            "first_name",
            "last_name",
            "email",
            "phone",
            "password1",
            "password2",
        )
        labels = {
            "first_name": "Yetkili adı",
            "last_name": "Yetkili soyadı",
            "email": "Kurumsal e-posta",
            "phone": "Telefon",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs["autocomplete"] = "new-password"
        self.fields["password2"].widget.attrs["autocomplete"] = "new-password"

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"].strip()).lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Bu e-posta adresiyle daha önce bir hesap oluşturulmuş.")
        return email

    @transaction.atomic
    def save(self, commit=True):
        if not commit:
            raise ValueError("Şirket başvurusu ilişkili kayıtlarıyla birlikte kaydedilmelidir.")

        user = super().save(commit=False)
        user.username = f"company_{uuid.uuid4().hex}"
        user.user_type = User.UserType.COMPANY
        user.email = self.cleaned_data["email"]
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        user.is_verified = False
        user.save()

        company = Company.objects.create(
            name=self.cleaned_data["company_name"],
            website=self.cleaned_data["website"],
            email=user.email,
            phone=user.phone,
            approval_status=Company.ApprovalStatus.PENDING,
            is_active=False,
            is_verified=False,
        )
        CompanyMembership.objects.create(
            user=user,
            company=company,
            role=CompanyMembership.Role.OWNER,
            is_active=False,
        )
        return user


class CompanyAuthenticationForm(forms.Form):
    email = forms.EmailField(
        label="E-posta",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )
    password = forms.CharField(
        label="Şifre",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email")
        password = cleaned_data.get("password")
        if email and password:
            email = User.objects.normalize_email(email.strip()).lower()
            cleaned_data["email"] = email
            company_user = (
                User.objects.filter(
                    email__iexact=email,
                    user_type=User.UserType.COMPANY,
                )
                .order_by("pk")
                .first()
            )
            username = company_user.username if company_user else f"missing_{uuid.uuid4().hex}"
            authenticated_user = authenticate(
                self.request,
                username=username,
                password=password,
            )
            if authenticated_user is None or authenticated_user != company_user:
                raise ValidationError(COMPANY_LOGIN_ERROR, code="invalid_login")

            can_login = active_company_memberships_for(authenticated_user).exists()
            if not can_login:
                raise ValidationError(COMPANY_LOGIN_ERROR, code="invalid_login")
            self.user_cache = authenticated_user
        return cleaned_data

    def get_user(self):
        return self.user_cache


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = (
            "name",
            "description",
            "website",
            "email",
            "phone",
            "logo",
            "category",
        )
