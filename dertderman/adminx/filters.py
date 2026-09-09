from django import forms
from django.db.models import Q

from accounts.models import User
from blog.models import Post
from companies.models import Company, CompanyCategory, CompanyNotification
from complaints.models import Complaint
from core.pagination import paginate


def choices(values):
    return [("", "Tümü"), *values]


class SearchForm(forms.Form):
    q = forms.CharField(label="Ara", required=False, max_length=180,
                        widget=forms.TextInput(attrs={"placeholder": "Arama yapın", "type": "search"}))


class ComplaintFilters(SearchForm):
    status = forms.ChoiceField(label="Durum", required=False, choices=choices(Complaint.Status.choices))
    company = forms.ModelChoiceField(label="Şirket", required=False, empty_label="Tüm şirketler",
                                    queryset=Company.objects.only("name").order_by("name", "pk"))


class ApplicationFilters(SearchForm):
    status = forms.ChoiceField(label="Başvuru durumu", required=False, choices=choices(Company.ApprovalStatus.choices))


class CompanyFilters(ApplicationFilters):
    category = forms.ModelChoiceField(label="Kategori", required=False, empty_label="Tüm kategoriler",
                                     queryset=CompanyCategory.objects.order_by("name", "pk"))
    verified = forms.ChoiceField(label="Doğrulama", required=False, choices=choices([("1", "Doğrulanmış"), ("0", "Doğrulanmamış")]))
    active = forms.ChoiceField(label="Aktiflik", required=False, choices=choices([("1", "Aktif"), ("0", "Pasif")]))


class UserFilters(SearchForm):
    role = forms.ChoiceField(label="Rol", required=False, choices=choices(User.UserType.choices))
    active = forms.ChoiceField(label="Aktiflik", required=False, choices=CompanyFilters.base_fields["active"].choices)


class BlogFilters(SearchForm):
    status = forms.ChoiceField(label="Durum", required=False, choices=choices(Post.Status.choices))


class EventFilters(SearchForm):
    kind = forms.ChoiceField(label="Olay türü", required=False, choices=choices(CompanyNotification.Kind.choices))
    period = forms.ChoiceField(label="Dönem", required=False, choices=choices([("7", "Son 7 gün")]))


def list_context(request, queryset, form_class, *, search_fields, fields=None,
                 ordering=("-created_at", "-pk"), kind="admin", defaults=None):
    data = request.GET.copy()
    if "q" not in data and "s" in data:
        data["q"] = data["s"]
    for key, value in (defaults or {}).items():
        if key not in data:
            data[key] = value
    form = form_class(data)
    if form.is_valid():
        term = form.cleaned_data["q"]
        if term:
            query = Q()
            for field in search_fields:
                query |= Q(**{f"{field}__icontains": term})
            queryset = queryset.filter(query)
        for parameter, field in (fields or {}).items():
            value = form.cleaned_data.get(parameter)
            if value not in (None, ""):
                if parameter in ("active", "verified"):
                    value = value == "1"
                queryset = queryset.filter(**{field: value})
        if form.cleaned_data.get("period") == "7":
            from datetime import timedelta
            from django.utils import timezone
            queryset = queryset.filter(created_at__gte=timezone.now() - timedelta(days=7))
    else:
        queryset = queryset.none()
    return {"filter_form": form, "page_obj": paginate(request, queryset.order_by(*ordering), kind)}
