from django.urls import path

from .views import interact


app_name = "assistant"

urlpatterns = [
    path(
        "etkilesim/",
        interact,
        name="interact",
    ),
]
