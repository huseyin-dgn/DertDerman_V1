from django.urls import path

from .views import public_company_detail, public_company_list, public_company_report


app_name = "companies_public"

urlpatterns = [
    path("", public_company_list, name="company_list"),
    path("<slug:slug>/raporla/", public_company_report, name="company_report"),
    path("<slug:slug>/", public_company_detail, name="company_detail"),
]
