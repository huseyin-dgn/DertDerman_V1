from django.urls import path

from .views import (
    about,
    community_rules,
    contact,
    cookie_policy,
    disclosure_notice,
    home,
    intro,
    intro_reset,
    privacy_policy,
    terms_of_use,
    faq,
    categories
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
path(
    "kategoriler/",
    categories,
    name="categories",
),
path(
    "cerez-politikasi/",
    cookie_policy,
    name="cookie_policy",
),
path(
    "kullanici-hizmet-sozlesmesi/",
    terms_of_use,
    name="terms_of_use",
),
path(
    "topluluk-kurallari/",
    community_rules,
    name="community_rules",
),
path(
    "sss/",
    faq,
    name="faq",
),
]