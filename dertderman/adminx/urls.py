
from django.urls import path
from . import blog_views, content_views, views
from .auth_views import AdminLoginView


app_name = "adminx"

urlpatterns = [
    path("giris/", AdminLoginView.as_view(), name="login"),

    path("sirketler/", content_views.company_list, name="company_list"),
    path(
        "sirketler/<int:pk>/duzenle/",
        content_views.company_edit,
        name="company_edit",
    ),
    path(
        "sirketler/<int:pk>/arsivle/",
        content_views.company_archive,
        name="company_archive",
    ),

    path(
        "sirket-basvurulari/",
        content_views.company_application_list,
        name="company_application_list",
    ),
    path(
        "sirket-basvurulari/<int:pk>/",
        content_views.company_application_detail,
        name="company_application_detail",
    ),

    path("kullanicilar/", content_views.user_list, name="user_list"),
    path(
        "kullanicilar/<int:pk>/",
        content_views.user_detail,
        name="user_detail",
    ),

    path("bildirimler/", views.notifications, name="notifications"),
    path(
        "bildirimler/<int:pk>/",
        views.notification_open,
        name="notification_open",
    ),
    path(
        "bildirimler/<int:pk>/okundu/",
        views.notification_read,
        name="notification_read",
    ),
    path(
        "bildirimler/tumunu-okundu/",
        views.notifications_read_all,
        name="notifications_read_all",
    ),

    path("aktivite/", views.activity, name="activity"),

    path(
        "audit-log/",
        views.audit_log_list,
        name="audit_log_list",
    ),

    path(
        "iletisim-talepleri/",
        views.contact_list,
        name="contact_list",
    ),
    path(
        "iletisim-talepleri/<int:pk>/",
        views.contact_detail,
        name="contact_detail",
    ),
    path(
        "iletisim-talepleri/<int:pk>/durum/",
        views.contact_status,
        name="contact_status",
    ),

    path(
        "ana-sayfa/",
        content_views.homepage_content,
        name="homepage_content",
    ),

    path("blog/", blog_views.post_list, name="blog_list"),
    path("blog/yeni/", blog_views.post_create, name="blog_create"),
    path(
        "blog/<int:pk>/duzenle/",
        blog_views.post_edit,
        name="blog_edit",
    ),
    path(
        "blog/<int:pk>/yayinla/",
        blog_views.post_publish,
        name="blog_publish",
    ),
    path(
        "blog/<int:pk>/sil/",
        blog_views.post_delete,
        name="blog_delete",
    ),

    path("sikayetler/", views.complaint_list, name="complaint_list"),
    path(
        "sikayetler/<int:pk>/",
        views.complaint_detail,
        name="complaint_detail",
    ),
    path(
        "sikayetler/<int:pk>/yayinla/",
        views.complaint_publish,
        name="complaint_publish",
    ),
    path(
        "sikayetler/<int:pk>/reddet/",
        views.complaint_reject,
        name="complaint_reject",
    ),
    path(
        "sikayetler/<int:pk>/cozuldu/",
        views.complaint_resolve,
        name="complaint_resolve",
    ),

    path(
        "raporlar/",
        views.report_list,
        name="report_list",
    ),
    path(
        "raporlar/<int:pk>/",
        views.report_detail,
        name="report_detail",
    ),
    path(
        "raporlar/<int:pk>/durum/",
        views.report_status,
        name="report_status",
    ),

    path("", views.home, name="home"),
]