from django.urls import path

from .views import (
    RegisterView,
    SecureLoginView,
    SecureLogoutView,
    SecurePasswordChangeView,
    account_entry,
    invalidate_history_session,
    profile,
    profile_edit,
    public_profile,
)


app_name = "accounts"

urlpatterns = [
    path("", account_entry, name="entry"),
    path("kayit/", RegisterView.as_view(), name="register"),
    path("giris/", SecureLoginView.as_view(), name="login"),
    path("cikis/", SecureLogoutView.as_view(), name="logout"),
    path("oturum/gecmis-sonlandir/", invalidate_history_session, name="history_invalidate"),
    path("profil/", profile, name="profile"),
    path(
        "kullanici/<str:username>/",
        public_profile,
        name="public_profile",
    ),
    path("profil/duzenle/", profile_edit, name="profile_edit"),
    path(
        "sifre-degistir/",
        SecurePasswordChangeView.as_view(),
        name="password_change",
    ),
]
