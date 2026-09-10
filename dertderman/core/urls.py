from django.urls import path

from .views import (
    about,
    contact,
    disclosure_notice,
    home,
    intro,
    intro_reset,
    privacy_policy,
)

app_name = "core"

urlpatterns = [
    path("intro/reset/", intro_reset, name="intro_reset"),
    path("intro/", intro, name="intro"),
    path("hakkimizda/", about, name="about"),
    path("bize-ulasin/", contact, name="contact"),
    path("gizlilik-politikasi/", privacy_policy, name="privacy_policy"),
    path("", home, name="home"),
    path(
    "kvkk-aydinlatma-metni/",
    disclosure_notice,
    name="disclosure_notice",
),
]