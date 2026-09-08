from django.urls import path

from .views import home, intro, intro_reset


app_name = "core"

urlpatterns = [
    path("intro/reset/", intro_reset, name="intro_reset"),
    path("intro/", intro, name="intro"),
    path("", home, name="home"),
]
