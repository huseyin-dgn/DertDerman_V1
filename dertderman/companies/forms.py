from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.models import User

from .models import Company, CompanyMembership


COMPANY_LOGIN_ERROR = "Kurumsal giriş bilgileri doğrulanamadı."
COMPANY_PENDING_ERROR = "Şirket hesabınız henüz onaylanmadı."
COMPANY_REJECTED_ERROR = "Şirket hesabınız kurumsal erişime uygun değil."


class CompanyRegistrationForm(UserCreationForm):
    company_name = forms.CharField(label="Şirket adı", max_length=255)
    first_name = forms.CharField(label="Yetkili adı", max_length=150)
    last_name = forms.CharField(label="Yetkili soyadı", max_length=150)
    email = forms.EmailField(label="Kurumsal e-posta")
    phone = forms.CharField(label="Telefon", max_length=20)
    website = forms.URLField(label="Web sitesi", required=False)

    field_order = (
        "company_name",
        "first_name",
        "last_name",
        "email",
        "phone",
        "website",
        "username",
        "password1",
        "password2",
    )

    class Meta:
        model = User
        fields = (
            "username",
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
            "username": "Kullanıcı adı",
        }

    @transaction.atomic
    def save(self, commit=True):
        if not commit:
            raise ValueError("Şirket başvurusu ilişkili kayıtlarıyla birlikte kaydedilmelidir.")

        user = super().save(commit=False)
        user.user_type = User.UserType.COMPANY
        user.email = User.objects.normalize_email(user.email)
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


class CompanyAuthenticationForm(AuthenticationForm):
    error_messages = {
        "invalid_login": COMPANY_LOGIN_ERROR,
        "inactive": COMPANY_LOGIN_ERROR,
    }

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.user_type != User.UserType.COMPANY:
            raise ValidationError(COMPANY_LOGIN_ERROR, code="invalid_login")

        memberships = CompanyMembership.objects.filter(user=user).select_related("company")
        if memberships.filter(
            is_active=True,
            company__is_active=True,
            company__approval_status=Company.ApprovalStatus.APPROVED,
        ).exists():
            return
        if memberships.filter(company__approval_status=Company.ApprovalStatus.PENDING).exists():
            raise ValidationError(COMPANY_PENDING_ERROR, code="company_pending")
        if memberships.filter(company__approval_status=Company.ApprovalStatus.REJECTED).exists():
            raise ValidationError(COMPANY_REJECTED_ERROR, code="company_rejected")
        raise ValidationError(COMPANY_LOGIN_ERROR, code="invalid_login")


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
