from django.urls import path

from . import panel_views


app_name = "companies"

urlpatterns = [
    path("", panel_views.dashboard, name="company_panel"),
    path("sikayetler/", panel_views.complaint_list, name="complaint_list"),
    path("sikayetler/<int:pk>/", panel_views.complaint_detail, name="complaint_detail"),
    path("sikayetler/<int:pk>/cevap/", panel_views.response_create, name="response_create"),
    path("sikayetler/<int:pk>/not/", panel_views.note_create, name="note_create"),
    path("cevaplar/", panel_views.responses, name="responses"),
    path("profil/", panel_views.profile, name="profile"),
    path("yetkililer/", panel_views.members, name="members"),
    path("bildirimler/", panel_views.notifications, name="notifications"),
    path("bildirimler/<int:pk>/", panel_views.notification_open, name="notification_open"),
    path("bildirimler/tumunu-okundu/", panel_views.notifications_read_all, name="notifications_read_all"),
    path("bildirimler/<int:pk>/okundu/", panel_views.notification_read, name="notification_read"),
    path("ayarlar/", panel_views.panel_settings, name="settings"),
    path("sirket-sec/", panel_views.switch_company, name="switch_company"),
    path("<slug:slug>/", panel_views.legacy_company_dashboard, name="company_panel_detail"),
]
