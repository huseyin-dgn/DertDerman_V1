from django.urls import path

from .views import company_panel, company_panel_detail


app_name = "companies"

urlpatterns = [
    path("", company_panel, name="company_panel"),
    path("<slug:slug>/", company_panel_detail, name="company_panel_detail"),
]
