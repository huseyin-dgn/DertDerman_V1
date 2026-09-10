from django import forms

from .models import ContactRequest


class ContactRequestForm(forms.ModelForm):
    class Meta:
        model = ContactRequest
        fields = ("name", "email", "request_type", "subject", "message")
        labels = {
            "name": "Ad Soyad", "email": "E-posta", "request_type": "Talep Türü",
            "subject": "Konu", "message": "Mesaj",
        }
        widgets = {
            "message": forms.Textarea(attrs={"rows": 7, "maxlength": 4000}),
            "subject": forms.TextInput(attrs={"maxlength": 180}),
        }

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean_subject(self):
        return self.cleaned_data["subject"].strip()

    def clean_message(self):
        return self.cleaned_data["message"].strip()
