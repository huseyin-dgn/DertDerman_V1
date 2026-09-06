from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("", include("core.urls")),
    path("", include("complaints.urls")),
    path("hesap/", include("accounts.urls")),
    path("panel/", include("dashboard.urls")),
    path("sirket-panel/", include("companies.urls")),
    path("sirketler/", include("companies.public_urls")),
    path("yonetim/", include("adminx.urls")),
    path("django-admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
