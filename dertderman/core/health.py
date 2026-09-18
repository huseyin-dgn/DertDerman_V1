import logging

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


logger = logging.getLogger(__name__)


@require_safe
@never_cache
def liveness(request):
    """
    Process-level probe.

    Database veya cache gibi harici servislere baglanmaz.
    Uygulama process'i HTTP istegine cevap verebiliyorsa 200 doner.
    """
    return JsonResponse(
        {
            "status": "ok",
        },
        status=200,
    )


@require_safe
@never_cache
def readiness(request):
    """
    Dependency-level probe.

    Production'da uygulamanin trafik kabul edebilmesi icin
    PostgreSQL ve cache backend'inin erisilebilir olmasi gerekir.

    Public response altyapi detaylarini aciga cikarmaz.
    Ayrintili hata server log'una yazilir.
    """
    healthy = True

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()

        if not result or result[0] != 1:
            raise RuntimeError(
                "Database readiness query returned an unexpected result."
            )

    except Exception:
        healthy = False

        logger.exception(
            "Readiness database check failed."
        )

    try:
        # Anahtarin mevcut olmasi gerekmez.
        # Bu istek cache backend'ine gercek bir baglanti kurar.
        cache.get(
            "__dertderman_readiness_probe__"
        )

    except Exception:
        healthy = False

        logger.exception(
            "Readiness cache check failed."
        )

    if not healthy:
        return JsonResponse(
            {
                "status": "unavailable",
            },
            status=503,
        )

    return JsonResponse(
        {
            "status": "ok",
        },
        status=200,
    )
