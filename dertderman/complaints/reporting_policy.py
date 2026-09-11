from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from core.models import AbuseAttempt

from .models import (
    ContentReport,
    CompanyReport,
    ReportRestriction,
    UserReport,
    UserViolation,
)


USER_REPORT_MAX_24H = 3
PROBATION_USER_REPORT_MAX_24H = 1

FALSE_REPORT_TRIGGER_24H = 3
PROBATION_DURATION = timedelta(days=3)
THIRD_DAY_START = timedelta(days=2)
FULL_BLOCK_DURATION = timedelta(days=7)

PERMANENT_CLOSE_FALSE_REPORT_THRESHOLD = 9
CATEGORY_CLOSE_THRESHOLD = 4


@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    message: str = ""
    code: str = ""
    until: object = None
    limit: int | None = None
    observed: int | None = None


def false_report_violations(user):
    """
    İçerik raporu veya kullanıcı raporu fark etmeksizin bütün
    doğrulanmış kötü niyetli/asilsiz raporlama ihlallerini tek havuzda döndürür.
    """
    return UserViolation.objects.filter(
        user=user,
        source_type=UserViolation.SourceType.FALSE_REPORT,
    )


def total_false_report_count(user):
    return false_report_violations(user).count()


def false_report_category_counts(user):
    qs = false_report_violations(user)
    return {
        "user_report": qs.filter(user_report__isnull=False).count(),
        "content_report": qs.filter(content_report__isnull=False).count(),
        "company_report": qs.filter(company_report__isnull=False).count(),
    }


def permanent_close_eligible(user):
    counts = false_report_category_counts(user)
    total = sum(counts.values())

    return (
        counts["user_report"] >= CATEGORY_CLOSE_THRESHOLD
        or counts["content_report"] >= CATEGORY_CLOSE_THRESHOLD
        or counts["company_report"] >= CATEGORY_CLOSE_THRESHOLD
        or total >= PERMANENT_CLOSE_FALSE_REPORT_THRESHOLD
    )


def active_full_block(user, now=None):
    now = now or timezone.now()

    return (
        ReportRestriction.objects
        .filter(
            user=user,
            kind=ReportRestriction.Kind.FULL_BLOCK,
            starts_at__lte=now,
            ends_at__gt=now,
        )
        .order_by(
            "-ends_at",
            "-pk",
        )
        .first()
    )


def active_probation(user, now=None):
    now = now or timezone.now()

    return (
        ReportRestriction.objects
        .filter(
            user=user,
            kind=ReportRestriction.Kind.PROBATION,
            starts_at__lte=now,
            ends_at__gt=now,
        )
        .order_by(
            "-starts_at",
            "-pk",
        )
        .first()
    )


def _log_policy_block(
    *,
    request,
    code,
    detail,
    limit=None,
    observed=None,
    until=None,
):
    """
    Core AbuseAttempt'a yeni enum eklemeden güvenlik geçmişine kayıt düşürür.
    event_type=OTHER kullanılır; gerçek kategori metadata.policy_code içindedir.
    """
    if not request or not request.user.is_authenticated:
        return None

    ip = request.META.get("REMOTE_ADDR", "")

    return AbuseAttempt.objects.create(
        user=request.user,
        event_type=AbuseAttempt.EventType.OTHER,
        ip_address=ip,
        path=(request.path or "")[:255],
        method=(request.method or "")[:10],
        detail=detail,
        metadata={
            "policy_code": code,
            "limit": limit,
            "observed": observed,
            "restriction_until": (
                until.isoformat()
                if until
                else None
            ),
        },
    )


def check_general_reporting_allowed(
    *,
    user,
    request=None,
):
    """
    Şikayet/yorum/kullanıcı raporlamalarının tamamı için 7 günlük
    FULL_BLOCK kontrolü.
    """
    now = timezone.now()
    restriction = active_full_block(
        user,
        now=now,
    )

    if not restriction:
        return PolicyResult(
            allowed=True
        )

    message = (
        "Hesabınız geçici moderasyon kısıtı altında. "
        "Bu süre boyunca raporlama işlemi yapamazsınız."
    )

    _log_policy_block(
        request=request,
        code="REPORTING_FULL_BLOCK",
        detail=(
            "Aktif 7 günlük şikayet/raporlama kısıtı nedeniyle "
            "raporlama işlemi engellendi."
        ),
        until=restriction.ends_at,
    )

    return PolicyResult(
        allowed=False,
        message=message,
        code="REPORTING_FULL_BLOCK",
        until=restriction.ends_at,
    )


def check_complaint_creation_allowed(
    *,
    user,
    request=None,
):
    """
    7 günlük FULL_BLOCK aktifken yeni şikayet oluşturulamaz.
    """
    now = timezone.now()
    restriction = active_full_block(
        user,
        now=now,
    )

    if not restriction:
        return PolicyResult(
            allowed=True
        )

    message = (
        "Hesabınız geçici moderasyon kısıtı altında. "
        "Bu süre boyunca yeni şikayet oluşturamazsınız."
    )

    _log_policy_block(
        request=request,
        code="COMPLAINT_FULL_BLOCK",
        detail=(
            "Aktif 7 günlük şikayet/raporlama kısıtı nedeniyle "
            "şikayet oluşturma işlemi engellendi."
        ),
        until=restriction.ends_at,
    )

    return PolicyResult(
        allowed=False,
        message=message,
        code="COMPLAINT_FULL_BLOCK",
        until=restriction.ends_at,
    )




def successful_reports_last_24h(user, now=None):
    now = now or timezone.now()
    since = now - timedelta(hours=24)

    return (
        UserReport.objects.filter(
            reporter=user,
            created_at__gte=since,
        ).count()
        + ContentReport.objects.filter(
            reporter=user,
            created_at__gte=since,
        ).count()
        + CompanyReport.objects.filter(
            reporter=user,
            created_at__gte=since,
        ).count()
    )


def check_user_report_allowed(
    *,
    user,
    request=None,
):
    """
    Normal durumda:
        son 24 saatte en fazla 3 kullanıcı raporu.

    PROBATION aktifse:
        son 24 saatte en fazla 1 kullanıcı raporu.

    FULL_BLOCK aktifse:
        kullanıcı raporu gönderilemez.
    """
    general = check_general_reporting_allowed(
        user=user,
        request=request,
    )

    if not general.allowed:
        return general

    now = timezone.now()
    since = now - timedelta(
        hours=24
    )

    probation = active_probation(
        user,
        now=now,
    )

    limit = (
        PROBATION_USER_REPORT_MAX_24H
        if probation
        else USER_REPORT_MAX_24H
    )

    if probation:
        report_count = successful_reports_last_24h(
            user,
            now=now,
        )
    else:
        report_count = (
            UserReport.objects
            .filter(
                reporter=user,
                created_at__gte=since,
            )
            .count()
        )

    if report_count < limit:
        return PolicyResult(
            allowed=True,
            limit=limit,
            observed=report_count,
        )

    if probation:
        message = (
            "Kötü niyetli raporlama geçmişiniz nedeniyle "
            "geçici olarak 24 saatte en fazla 1 kullanıcı "
            "raporu gönderebilirsiniz."
        )
        code = "USER_REPORT_PROBATION_LIMIT"
    else:
        message = (
            "24 saat içinde en fazla 3 kullanıcı "
            "raporlayabilirsiniz."
        )
        code = "USER_REPORT_RATE_LIMIT_24H"

    _log_policy_block(
        request=request,
        code=code,
        detail=(
            "Kullanıcı raporlama 24 saatlik limit nedeniyle engellendi."
        ),
        limit=limit,
        observed=report_count,
        until=(
            probation.ends_at
            if probation
            else None
        ),
    )

    return PolicyResult(
        allowed=False,
        message=message,
        code=code,
        until=(
            probation.ends_at
            if probation
            else None
        ),
        limit=limit,
        observed=report_count,
    )


def apply_false_report_penalties(
    violation,
):
    """
    FALSE_REPORT ihlali oluştuğu anda çağrılır.

    1) Son 24 saatte 3 FALSE_REPORT doğrulanırsa:
       3 günlük raporlama gözetimi başlatılır.
       Bu gözetimde kullanıcı raporu limiti 1/24h olur.

    2) Gözetimin üçüncü gününde (başlangıçtan 48-72 saat sonra)
       yeni bir FALSE_REPORT doğrulanırsa:
       7 günlük şikayet + tüm raporlama kısıtı oluşturulur.

    Bu işlemler UserViolation'dan ayrıdır ve ReportRestriction tablosunda
    ayrıca kayıt altında tutulur.
    """
    if (
        violation.source_type
        != UserViolation.SourceType.FALSE_REPORT
    ):
        return None

    user = violation.user
    now = violation.created_at or timezone.now()

    full_block = active_full_block(
        user,
        now=now,
    )

    if full_block:
        return full_block

    probation = active_probation(
        user,
        now=now,
    )

    if probation:
        third_day_start = (
            probation.starts_at
            + THIRD_DAY_START
        )

        if (
            third_day_start
            <= now
            < probation.ends_at
        ):
            return ReportRestriction.objects.create(
                user=user,
                kind=ReportRestriction.Kind.FULL_BLOCK,
                starts_at=now,
                ends_at=(
                    now
                    + FULL_BLOCK_DURATION
                ),
                trigger_violation=violation,
                reason=(
                    "Kullanıcı, kötü niyetli raporlama gözetiminin "
                    "üçüncü gününde yeniden FALSE_REPORT ihlali aldı. "
                    "7 günlük şikayet ve raporlama kısıtı uygulandı."
                ),
            )

        return probation

    since = (
        now
        - timedelta(
            hours=24
        )
    )

    recent_false_count = (
        false_report_violations(user)
        .filter(
            created_at__gte=since,
            created_at__lte=now,
        )
        .count()
    )

    if (
        recent_false_count
        >= FALSE_REPORT_TRIGGER_24H
    ):
        return ReportRestriction.objects.create(
            user=user,
            kind=ReportRestriction.Kind.PROBATION,
            starts_at=now,
            ends_at=(
                now
                + PROBATION_DURATION
            ),
            trigger_violation=violation,
            reason=(
                "Son 24 saat içinde 3 doğrulanmış kötü niyetli/"
                "asılsız raporlama ihlali oluştu. Kullanıcı raporu "
                "limiti geçici olarak 1/24 saate düşürüldü."
            ),
        )

    return None
