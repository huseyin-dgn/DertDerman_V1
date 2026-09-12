from django.urls import path

from .password_reset_views import (
    PasswordResetDoneView,
    PasswordResetRequestView,
    SecurePasswordResetCompleteView,
    SecurePasswordResetConfirmView,
)
from .views import (
    RegisterView,
    SecureLoginView,
    SecureLogoutView,
    SecurePasswordChangeView,
    account_entry,
    email_verification_confirm,
    email_verification_pending,
    invalidate_history_session,
    profile,
    profile_edit,
    public_profile,
)


app_name = "accounts"

urlpatterns = [
    path("", account_entry, name="entry"),
    path("kayit/", RegisterView.as_view(), name="register"),
    path(
        "eposta-dogrulama-bekleniyor/",
        email_verification_pending,
        name="email_verification_pending",
    ),
    path(
        "eposta-dogrula/<str:token>/",
        email_verification_confirm,
        name="email_verification_confirm",
    ),
    path("giris/", SecureLoginView.as_view(), name="login"),
    path(
        "sifremi-unuttum/",
        PasswordResetRequestView.as_view(),
        name="password_reset",
    ),
    path(
        "sifre-sifirlama/gonderildi/",
        PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "sifre-sifirla/<uidb64>/<token>/",
        SecurePasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "sifre-sifirlama/tamamlandi/",
        SecurePasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("cikis/", SecureLogoutView.as_view(), name="logout"),
    path(
        "oturum/gecmis-sonlandir/",
        invalidate_history_session,
        name="history_invalidate",
    ),
    path("profil/", profile, name="profile"),
    path(
        "kullanici/<str:username>/",
        public_profile,
        name="public_profile",
    ),
    path(
        "profil/duzenle/",
        profile_edit,
        name="profile_edit",
    ),
    path(
        "sifre-degistir/",
        SecurePasswordChangeView.as_view(),
        name="password_change",
    ),
]
