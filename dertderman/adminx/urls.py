from django.urls import path

from . import blog_views, content_views, views
from .auth_views import AdminLoginView


app_name = "adminx"

urlpatterns = [
    path("giris/", AdminLoginView.as_view(), name="login"),
    path("sirketler/", content_views.company_list, name="company_list"),
    path("sirketler/<int:pk>/duzenle/", content_views.company_edit, name="company_edit"),
    path("kullanicilar/", content_views.user_list, name="user_list"),
    path("ana-sayfa/", content_views.homepage_content, name="homepage_content"),
    path("blog/", blog_views.post_list, name="blog_list"),
    path("blog/yeni/", blog_views.post_create, name="blog_create"),
    path("blog/<int:pk>/duzenle/", blog_views.post_edit, name="blog_edit"),
    path("blog/<int:pk>/yayinla/", blog_views.post_publish, name="blog_publish"),
    path("", views.home, name="home"),
    path("sikayetler/", views.complaint_list, name="complaint_list"),
    path("sikayetler/<int:pk>/", views.complaint_detail, name="complaint_detail"),
    path("sikayetler/<int:pk>/yayinla/", views.complaint_publish, name="complaint_publish"),
    path("sikayetler/<int:pk>/reddet/", views.complaint_reject, name="complaint_reject"),
]
