from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from core.views import custom_404


urlpatterns = [
    path("", include("core.urls")),
    path("blog/", include("blog.urls")),
    path("", include("complaints.urls")),
    path("hesap/", include("accounts.urls")),
    path("kurumsal/", include("companies.auth_urls")),
    path("panel/", include("dashboard.urls")),
    path("bildirimler/", include("notifications.urls")),
    path("sirket-panel/", include("companies.urls")),
    path("sirketler/", include("companies.public_urls")),
    path("yonetim/", include("adminx.urls")),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )

handler404 = "core.views.custom_404"


urlpatterns += [
    path("<path:unmatched_path>", custom_404, name="custom_404"),
]
