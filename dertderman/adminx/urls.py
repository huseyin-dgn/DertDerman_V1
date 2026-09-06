from django.urls import path

from .views import home


app_name = "adminx"

urlpatterns = [
    path("", home, name="home"),
]
