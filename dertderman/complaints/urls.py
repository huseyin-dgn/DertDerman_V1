from django.urls import path

from .views import (
    complaint_create,
    complaint_detail,
    complaint_list,
    complaint_resolve,
    complaint_edit,
    complaint_withdraw,
    complaint_like_toggle,
    complaint_react,
    complaint_comment_create,
    complaint_comment_delete,
    public_complaint_detail,
    public_complaint_list,
)


app_name = "complaints"

urlpatterns = [
    path("sikayetler/", public_complaint_list, name="public_list"),
    path("sikayetler/<int:pk>/", public_complaint_detail, name="public_detail"),
    path("sikayetler/<int:pk>/begen/", complaint_like_toggle, name="like_toggle"),
    path("sikayetler/<int:pk>/tepki/", complaint_react, name="react"),
    path("sikayetler/<int:pk>/yorum/", complaint_comment_create, name="comment_create"),
    path("sikayetler/<int:pk>/yorum/<int:comment_pk>/sil/", complaint_comment_delete, name="comment_delete"),
    path("sikayetlerim/", complaint_list, name="list"),
    path("sikayetlerim/<int:pk>/", complaint_detail, name="detail"),
    path("sikayetlerim/<int:pk>/cozuldu/", complaint_resolve, name="resolve"),
    path("sikayetlerim/<int:pk>/duzenle/", complaint_edit, name="edit"),
    path("sikayetlerim/<int:pk>/geri-cek/", complaint_withdraw, name="withdraw"),
    path("sikayet-olustur/", complaint_create, name="create"),
]
