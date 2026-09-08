from django import forms

from .models import Company, CompanyCategory


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
    class Meta:
        model = Company
        fields = ("name", "description", "logo", "website", "phone", "email", "category")
        labels = {"name": "Şirket adı", "description": "Açıklama", "logo": "Şirket logosu",
            "website": "Web sitesi", "phone": "Telefon", "email": "İletişim e-postası", "category": "Kategori"}
        widgets = {"description": forms.Textarea(attrs={"rows": 5, "maxlength": 5000})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = CompanyCategory.objects.filter(is_active=True)
        self.fields["description"].max_length = 5000
        self.fields["logo"].help_text = "PNG, JPEG veya WebP; en fazla 2 MB."

    def clean_description(self):
        value = self.cleaned_data["description"].strip()
        if len(value) > 5000:
            raise forms.ValidationError("Açıklama en fazla 5000 karakter olabilir.")
        return value

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo and hasattr(logo, "image"):
            if logo.size > 2 * 1024 * 1024 or logo.image.format not in {"PNG", "JPEG", "WEBP"}:
                raise forms.ValidationError("En fazla 2 MB boyutunda PNG, JPEG veya WebP yükleyin.")
        return logo
