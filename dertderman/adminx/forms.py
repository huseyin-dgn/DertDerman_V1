from django import forms

from companies.models import Company


class CompanyContentForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ("name", "description", "website", "email", "phone")
        labels = {"name": "Şirket adı", "description": "Açıklama", "website": "Web sitesi", "email": "E-posta", "phone": "Telefon"}
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}
