from django import forms

from companies.models import Company

from .models import Complaint


class ComplaintCreateForm(forms.ModelForm):
    class Meta:
        model = Complaint
        fields = ("company", "title", "description")
        labels = {
            "company": "Şirket",
            "title": "Şikayet başlığı",
            "description": "Açıklama",
        }
        help_texts = {
            "title": "5-150 karakter arasında kısa ve net bir başlık yazın.",
            "description": "Sorunu en az 20 karakterle anlaşılır şekilde açıklayın.",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.filter(is_active=True).order_by(
            "name"
        )
        self.fields["company"].empty_label = "Şirket seçin"

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if len(title) < 5:
            raise forms.ValidationError("Başlık en az 5 karakter olmalıdır.")
        return title

    def clean_description(self):
        description = self.cleaned_data["description"].strip()
        if len(description) < 20:
            raise forms.ValidationError("Açıklama en az 20 karakter olmalıdır.")
        return description
