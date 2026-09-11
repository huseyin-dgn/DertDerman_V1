from django import forms

from companies.models import Company

from .models import Complaint, ComplaintComment, CompanyReport, ContentReport, UserReport


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
            "title": forms.TextInput(
                attrs={
                    "maxlength": 150,
                    "data-character-count": "",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 8,
                    "data-character-count": "",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["company"].queryset = Company.objects.filter(
            is_active=True
        ).order_by("name")

        self.fields["company"].empty_label = "Şirket seçin"

    def clean_title(self):
        title = self.cleaned_data["title"].strip()

        if len(title) < 5:
            raise forms.ValidationError(
                "Başlık en az 5 karakter olmalıdır."
            )

        return title

    def clean_description(self):
        description = self.cleaned_data["description"].strip()

        if len(description) < 20:
            raise forms.ValidationError(
                "Açıklama en az 20 karakter olmalıdır."
            )

        return description


class ComplaintEditForm(ComplaintCreateForm):
    class Meta(ComplaintCreateForm.Meta):
        pass


class ComplaintCommentForm(forms.ModelForm):
    class Meta:
        model = ComplaintComment
        fields = ("body",)
        labels = {
            "body": "Yorumunuz",
        }
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 4,
                    "maxlength": 1000,
                    "placeholder": (
                        "Deneyimle ilgili görüşünüzü paylaşın…"
                    ),
                    "data-character-count": "",
                }
            )
        }

    def clean_body(self):
        body = (
            self.cleaned_data.get("body") or ""
        ).strip()

        if not body:
            raise forms.ValidationError(
                "Yorum boş bırakılamaz."
            )

        return body


class ContentReportForm(forms.ModelForm):
    class Meta:
        model = ContentReport
        fields = (
            "reason",
            "description",
        )

        labels = {
            "reason": "Raporlama nedeni",
            "description": "Açıklama",
        }

        help_texts = {
            "description": (
                "İsterseniz neden raporladığınızı kısa şekilde açıklayın."
            ),
        }

        widgets = {
            "reason": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "maxlength": 1000,
                    "placeholder": (
                        "Bu içeriği neden raporluyorsunuz?"
                    ),
                    "data-character-count": "",
                }
            ),
        }

    def clean_description(self):
        description = (
            self.cleaned_data.get("description") or ""
        ).strip()

        return description

class UserReportForm(forms.ModelForm):
    class Meta:
        model = UserReport
        fields = (
            "reason",
            "description",
        )

        labels = {
            "reason": "Raporlama nedeni",
            "description": "Açıklama",
        }

        help_texts = {
            "description": (
                "İsterseniz neden raporladığınızı kısa şekilde açıklayın."
            ),
        }

        widgets = {
            "reason": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "maxlength": 1000,
                    "placeholder": (
                        "Bu kullanıcıyı neden raporluyorsunuz?"
                    ),
                    "data-character-count": "",
                }
            ),
        }

    def clean_description(self):
        return (
            self.cleaned_data.get("description") or ""
        ).strip()


class CompanyReportForm(forms.ModelForm):
    class Meta:
        model = CompanyReport
        fields = (
            "reason",
            "description",
        )
        labels = {
            "reason": "Raporlama nedeni",
            "description": "Açıklama",
        }
        help_texts = {
            "description": (
                "İsterseniz şirketi neden raporladığınızı kısa şekilde açıklayın."
            ),
        }
        widgets = {
            "reason": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "maxlength": 1000,
                    "placeholder": "Bu şirketi neden raporluyorsunuz?",
                }
            ),
        }

    def clean_description(self):
        return (self.cleaned_data.get("description") or "").strip()
