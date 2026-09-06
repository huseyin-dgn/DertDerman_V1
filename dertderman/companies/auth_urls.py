from django.urls import path

from .auth_views import CompanyLoginView, company_register


app_name = "company_auth"

urlpatterns = [
    path("giris/", CompanyLoginView.as_view(), name="login"),
    path("kayit/", company_register, name="register"),
]
