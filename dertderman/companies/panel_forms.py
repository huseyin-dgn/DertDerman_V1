from django import forms
from core.images import secure_uploaded_image

from .models import Company, CompanyCategory
from .avatars import COMPANY_AVATAR_CHOICES


class CompanyResponseForm(forms.Form):
    body = forms.CharField(label="Şirket cevabı", max_length=5000, strip=True,
        widget=forms.Textarea(attrs={"rows": 5, "placeholder": "Süreci, çözüm önerinizi ve sonraki adımı paylaşın."}))


class InternalCompanyNoteForm(forms.Form):
    body = forms.CharField(label="Dahili not", max_length=3000, strip=True,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Yalnızca şirket yetkililerinizin görebileceği bir not yazın."}))


class ComplaintFilterForm(forms.Form):
    q = forms.CharField(label="Şikayet ara", max_length=150, required=False,
        widget=forms.SearchInput(attrs={"placeholder": "Başlık veya içerikte ara"}))
    state = forms.ChoiceField(label="Durum", required=False, choices=(
        ("", "Tümü"), ("waiting", "Cevap bekleyen"), ("answered", "Cevaplanan"), ("resolved", "Çözülen")))
    start = forms.DateField(label="Başlangıç tarihi", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="Bitiş tarihi", required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["start"] > data["end"]:
            raise forms.ValidationError("Başlangıç tarihi bitiş tarihinden sonra olamaz.")
        return data


class CompanyProfileForm(forms.ModelForm):
    LOCKED_IDENTITY_ERROR = (
        "Onaylanmış şirketin kimlik bilgileri panelden değiştirilemez."
    )

    selected_avatar = forms.ChoiceField(
        label="Kurumsal simge", choices=COMPANY_AVATAR_CHOICES, required=False,
        widget=forms.RadioSelect,
    )
    class Meta:
        model = Company
        fields = ("name", "description", "logo", "selected_avatar", "website", "phone", "email", "category")
        labels = {"name": "Şirket adı", "description": "Açıklama", "logo": "Şirket logosu",
            "website": "Web sitesi", "phone": "Telefon", "email": "İletişim e-postası", "category": "Kategori"}
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5, "maxlength": 5000}),
            "logo": forms.FileInput(attrs={
                "class": "cp-logo-native-input",
                "accept": "image/png,image/jpeg,image/webp",
            }),
        }

    def __init__(self, *args, **kwargs):
        files = kwargs.get("files") or (args[1] if len(args) > 1 else None)
        raw_logo = files.get("logo") if files else None
        self._logo_mime = getattr(raw_logo, "content_type", "")
        super().__init__(*args, **kwargs)
        self.locked_fields = set()
        if self.instance and self.instance.approval_status == Company.ApprovalStatus.APPROVED:
            self.locked_fields.update(
                ("name", "category", "email")
            )

            # Logo ve kurumsal avatar tek bir görsel kimlik
            # olarak değerlendirilir. Bunlardan biri daha önce
            # seçildiyse ikisi de şirket panelinde kilitlenir.
            if (
                self.instance.logo
                or self.instance.selected_avatar
            ):
                self.locked_fields.update(
                    ("logo", "selected_avatar")
                )

        for field_name in self.locked_fields:
            self.fields.pop(field_name, None)

        if "category" in self.fields:
            self.fields["category"].queryset = CompanyCategory.objects.filter(is_active=True)
        self.fields["description"].max_length = 5000
        if "logo" in self.fields:
            self.fields["logo"].help_text = "PNG, JPEG veya WebP; en fazla 3 MB."

    def _locked_field_change_attempted(self):
        if not self.is_bound:
            return False

        comparisons = {
            "name": lambda value: value.strip() != self.instance.name,
            "email": lambda value: value.strip().casefold()
            != (self.instance.email or "").strip().casefold(),
            "category": lambda value: value.strip()
            != (str(self.instance.category_id) if self.instance.category_id else ""),
            "selected_avatar": lambda value: value.strip()
            != (self.instance.selected_avatar or ""),
        }

        for field_name, differs in comparisons.items():
            if field_name in self.locked_fields and field_name in self.data:
                if differs(self.data.get(field_name, "") or ""):
                    return True

        if "logo" in self.locked_fields and self.files.get("logo"):
            return True

        if (
            "logo" in self.locked_fields
            and (self.data.get("logo-clear") or "").strip().lower()
            in {"1", "true", "on", "yes"}
        ):
            return True

        return False

    def clean(self):
        cleaned_data = super().clean()
        if self._locked_field_change_attempted():
            raise forms.ValidationError(self.LOCKED_IDENTITY_ERROR)
        return cleaned_data

    def clean_description(self):
        value = self.cleaned_data["description"].strip()
        if len(value) > 5000:
            raise forms.ValidationError("Açıklama en fazla 5000 karakter olabilir.")
        return value

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        return secure_uploaded_image(logo, supplied_mime=self._logo_mime)
