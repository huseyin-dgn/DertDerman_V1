from django.urls import path

from .email_change_views import (
    EmailChangeCompleteView,
    EmailChangePendingView,
    EmailChangeRequestView,
    email_change_confirm,
)
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
    email_verification_resend,
    email_verification_resend_current,
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
    path(
        "eposta-dogrulama/yeniden-gonder/",
        email_verification_resend,
        name="email_verification_resend",
    ),
    path(
        "eposta-dogrulama/tekrar-gonder/",
        email_verification_resend_current,
        name="email_verification_resend_current",
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
    path(
        "eposta-degistir/",
        EmailChangeRequestView.as_view(),
        name="email_change",
    ),
    path(
        "eposta-degistirme/bekleniyor/",
        EmailChangePendingView.as_view(),
        name="email_change_pending",
    ),
    path(
        "eposta-degistir/onayla/<str:token>/",
        email_change_confirm,
        name="email_change_confirm",
    ),
    path(
        "eposta-degistirme/tamamlandi/",
        EmailChangeCompleteView.as_view(),
        name="email_change_complete",
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
