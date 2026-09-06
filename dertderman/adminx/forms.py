from django import forms

from companies.models import Company


class CompanyContentForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ("name", "description", "website", "email", "phone")
        labels = {"name": "Şirket adı", "description": "Açıklama", "website": "Web sitesi", "email": "E-posta", "phone": "Telefon"}
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}


class CompanyApprovalActionForm(forms.Form):
    class Action:
        APPROVE = "approve"
        REJECT = "reject"

    action = forms.ChoiceField(
        choices=((Action.APPROVE, "Onayla"), (Action.REJECT, "Reddet"))
    )
