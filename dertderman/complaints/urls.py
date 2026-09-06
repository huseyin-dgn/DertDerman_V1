from django.urls import path

from .views import complaint_create, complaint_detail, complaint_list


app_name = "complaints"

urlpatterns = [
    path("sikayetlerim/", complaint_list, name="list"),
    path("sikayetlerim/<int:pk>/", complaint_detail, name="detail"),
    path("sikayet-olustur/", complaint_create, name="create"),
]
