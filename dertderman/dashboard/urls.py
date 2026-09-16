from django.urls import path

from .views import (
    dermans,
    home,
)


app_name = "dashboard"


urlpatterns = [
    path(
        "",
        home,
        name="home",
    ),

    path(
        "dermanlarim/",
        dermans,
        name="dermans",
    ),
]