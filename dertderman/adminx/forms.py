from django import forms

from companies.avatars import COMPANY_AVATAR_CHOICES
from companies.models import Company
from core.images import secure_uploaded_image
from core.models import ContactRequest


class CompanyContentForm(
    forms.ModelForm
):
    selected_avatar = forms.ChoiceField(
        label="Kurumsal simge",
        choices=COMPANY_AVATAR_CHOICES,
        required=False,
        widget=forms.RadioSelect,
    )

    class Meta:
        model = Company

        fields = (
            "name",
            "category",
            "description",
            "logo",
            "selected_avatar",
            "website",
            "email",
            "phone",
        )

        labels = {
            "name":
                "Şirket adı",

            "category":
                "Şirket kategorisi",

            "description":
                "Açıklama",

            "logo":
                "Şirket logosu",

            "website":
                "Web sitesi",

            "email":
                "E-posta",

            "phone":
                "Telefon",
        }

        widgets = {
            "description":
                forms.Textarea(
                    attrs={
                        "rows": 5,
                    }
                )
        }

    def __init__(self, *args, **kwargs):
        files = kwargs.get("files") or (args[1] if len(args) > 1 else None)
        raw_logo = files.get("logo") if files else None
        self._logo_mime = getattr(raw_logo, "content_type", "")
        super().__init__(*args, **kwargs)
        self.fields["logo"].help_text = "PNG, JPEG veya WebP; en fazla 3 MB."

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        return secure_uploaded_image(logo, supplied_mime=self._logo_mime)

    def clean(self):
        cleaned_data = super().clean()
        uploaded_logo = bool(self.files.get("logo"))
        selected_avatar = cleaned_data.get("selected_avatar")
        if uploaded_logo and selected_avatar:
            raise forms.ValidationError(
                "Şirket logosu veya kurumsal simgeden yalnızca birini seçebilirsiniz."
            )
        if uploaded_logo:
            cleaned_data["selected_avatar"] = ""
        elif selected_avatar:
            cleaned_data["logo"] = False
        if cleaned_data.get("logo") and cleaned_data.get("selected_avatar"):
            raise forms.ValidationError(
                "Şirket logosu veya kurumsal simgeden yalnızca birini seçebilirsiniz."
            )
        return cleaned_data


class CompanyApprovalActionForm(
    forms.Form
):
    class Action:
        APPROVE = "approve"
        REJECT = "reject"

    action = forms.ChoiceField(
        choices=(
            (
                Action.APPROVE,
                "Onayla",
            ),
            (
                Action.REJECT,
                "Reddet",
            ),
        )
    )

    rejection_reason = forms.CharField(
        label="Red nedeni",
        required=False,
        max_length=1000,
        strip=True,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "maxlength": 1000,
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()

        if (
            cleaned_data.get("action")
            == self.Action.REJECT
            and not cleaned_data.get("rejection_reason")
        ):
            self.add_error(
                "rejection_reason",
                "Şirket başvurusu reddedilirken neden belirtilmelidir.",
            )

        return cleaned_data


class ContactStatusForm(
    forms.Form
):
    status = forms.ChoiceField(
        label="Durum",
        choices=(
            ContactRequest
            .Status
            .choices
        ),
    )

class DermanPublishForm(forms.Form):
    moderation_note = forms.CharField(
        label="İnceleme notu",
        required=False,
        max_length=1000,
        strip=True,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "maxlength": 1000,
                "placeholder": (
                    "İsteğe bağlı yönetim notu"
                ),
            }
        ),
    )


class DermanRejectForm(forms.Form):
    moderation_note = forms.CharField(
        label="Ret nedeni",
        required=True,
        max_length=1000,
        strip=True,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "maxlength": 1000,
                "placeholder": (
                    "Dermanın neden reddedildiğini yazın"
                ),
            }
        ),
    )
