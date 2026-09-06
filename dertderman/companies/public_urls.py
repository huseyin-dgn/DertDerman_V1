from django.urls import path

from .views import public_company_detail, public_company_list


app_name = "companies_public"

urlpatterns = [
    path("", public_company_list, name="company_list"),
    path("<slug:slug>/", public_company_detail, name="company_detail"),
]
