from django.urls import path

from .health import (
    liveness,
    readiness,
)

from .views import (
    about,
    advertising,
    advertising_payment_preview,
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
    for_companies,
    categories
)

app_name = "core"

urlpatterns = [
    path(
        "health/live/",
        liveness,
        name="health_live",
    ),
    path(
        "health/ready/",
        readiness,
        name="health_ready",
    ),
    path("intro/reset/", intro_reset, name="intro_reset"),
    path("intro/", intro, name="intro"),
    path("reklam-ver/", advertising, name="advertising"),
    path(
        "reklam-ver/odeme/",
        advertising_payment_preview,
        name="advertising_payment",
    ),
    path("hakkimizda/", about, name="about"),
    path("firmalar-icin/", for_companies, name="for_companies"),
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
