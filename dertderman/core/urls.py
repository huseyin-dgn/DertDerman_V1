from django.urls import path

from .views import about, contact, home, intro, intro_reset


app_name = "core"

urlpatterns = [
    path("intro/reset/", intro_reset, name="intro_reset"),
    path("intro/", intro, name="intro"),
    path("hakkimizda/", about, name="about"),
    path("bize-ulasin/", contact, name="contact"),
    path("", home, name="home"),
]
