from django.urls import path

from .views import (
    complaint_create,
    complaint_detail,
    complaint_list,
    public_complaint_detail,
    public_complaint_list,
)


app_name = "complaints"

urlpatterns = [
    path("sikayetler/", public_complaint_list, name="public_list"),
    path("sikayetler/<int:pk>/", public_complaint_detail, name="public_detail"),
    path("sikayetlerim/", complaint_list, name="list"),
    path("sikayetlerim/<int:pk>/", complaint_detail, name="detail"),
    path("sikayet-olustur/", complaint_create, name="create"),
]
