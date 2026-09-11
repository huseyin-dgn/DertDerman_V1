
from datetime import timedelta
from difflib import SequenceMatcher
import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from django.utils import timezone

from core.models import AbuseAttempt

from .models import Complaint


MAX_COMPLAINTS_10_MINUTES = 2
MAX_COMPLAINTS_1_HOUR = 3
MAX_COMPLAINTS_24_HOURS = 5

SAME_COMPANY_COOLDOWN_MINUTES = 30

NEW_ACCOUNT_AGE_HOURS = 24
NEW_ACCOUNT_MAX_24_HOURS = 2

MAX_OPEN_COMPLAINTS = 5

SIMILARITY_THRESHOLD = 0.85

MIN_FORM_FILL_SECONDS = 1.0

REJECTION_LOOKBACK_DAYS = 10
REJECTION_THRESHOLD = 3

REJECTION_RESTRICTION_DAYS = 3
REJECTION_RESTRICTED_MAX_24_HOURS = 1

FORM_SESSION_KEY = "complaint_form_opened_at"


@dataclass(frozen=True)
class ComplaintAntiAbuseResult:
    allowed: bool
    message: str = ""
    event_type: str = ""
    metadata: dict | None = None


def _allow():
    return ComplaintAntiAbuseResult(
        allowed=True,
    )


def get_client_ip(request):
    raw_ip = (
        request.META.get("REMOTE_ADDR")
        or ""
    ).strip()

    if not raw_ip:
        return None

    try:
        return str(
            ipaddress.ip_address(raw_ip)
        )
    except ValueError:
        return None


def log_abuse_attempt(
    *,
    request,
    event_type,
    detail,
    metadata=None,
):
    user = (
        request.user
        if request.user.is_authenticated
        else None
    )

    attempt = AbuseAttempt.objects.create(
        user=user,
        event_type=event_type,
        ip_address=get_client_ip(request),
        path=(request.path or "")[:255],
        method=(request.method or "")[:10],
        detail=detail,
        metadata=metadata or {},
    )

    from notifications.services import notify_admins_abuse_attempt

    notify_admins_abuse_attempt(attempt)

    return attempt


def _block(
    *,
    request,
    event_type,
    message,
    detail,
    metadata=None,
):
    log_abuse_attempt(
        request=request,
        event_type=event_type,
        detail=detail,
        metadata=metadata,
    )

    return ComplaintAntiAbuseResult(
        allowed=False,
        message=message,
        event_type=event_type,
        metadata=metadata or {},
    )


def mark_complaint_form_opened(request):
    request.session[FORM_SESSION_KEY] = (
        timezone.now().timestamp()
    )

    request.session.modified = True


def _form_fill_seconds(request):
    opened_at = request.session.get(
        FORM_SESSION_KEY
    )

    if opened_at is None:
        return None

    try:
        opened_timestamp = float(
            opened_at
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    return max(
        0.0,
        timezone.now().timestamp()
        - opened_timestamp,
    )


def reset_complaint_form_timer(request):
    request.session.pop(
        FORM_SESSION_KEY,
        None,
    )

    request.session.modified = True


def normalize_complaint_text(text):
    text = unicodedata.normalize(
        "NFKC",
        text or "",
    )

    text = text.casefold()

    text = re.sub(
        r"[^\w\s]",
        " ",
        text,
        flags=re.UNICODE,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def compact_complaint_text(text):
    normalized = normalize_complaint_text(
        text
    )

    return re.sub(
        r"\s+",
        "",
        normalized,
    )


def _combined_content(
    title,
    description,
):
    normalized_title = (
        normalize_complaint_text(
            title
        )
    )

    normalized_description = (
        normalize_complaint_text(
            description
        )
    )

    return (
        f"{normalized_title} "
        f"{normalized_description}"
    ).strip()


def _rejection_restriction(
    user,
    now,
):
    lookback_start = (
        now
        - timedelta(
            days=REJECTION_LOOKBACK_DAYS
        )
    )

    rejected = (
        Complaint.objects
        .filter(
            user=user,
            status=Complaint.Status.REJECTED,
            updated_at__gte=lookback_start,
        )
        .order_by(
            "-updated_at",
            "-pk",
        )
    )

    rejected_count = rejected.count()

    if rejected_count < REJECTION_THRESHOLD:
        return {
            "active": False,
            "rejected_count": rejected_count,
            "until": None,
        }

    last_rejected_at = (
        rejected
        .values_list(
            "updated_at",
            flat=True,
        )
        .first()
    )

    if not last_rejected_at:
        return {
            "active": False,
            "rejected_count": rejected_count,
            "until": None,
        }

    restriction_until = (
        last_rejected_at
        + timedelta(
            days=REJECTION_RESTRICTION_DAYS
        )
    )

    return {
        "active": now < restriction_until,
        "rejected_count": rejected_count,
        "until": restriction_until,
    }


def _find_duplicate_or_similar_complaint(
    *,
    user,
    company,
    title,
    description,
):
    current_description = (
        normalize_complaint_text(
            description
        )
    )

    current_combined = (
        _combined_content(
            title,
            description,
        )
    )

    current_compact_description = (
        compact_complaint_text(
            description
        )
    )

    current_compact_combined = (
        compact_complaint_text(
            f"{title} {description}"
        )
    )

    if not current_description:
        return None

    complaints = (
        Complaint.objects
        .filter(
            user=user,
            company=company,
        )
        .only(
            "pk",
            "title",
            "description",
        )
        .order_by(
            "-created_at",
            "-pk",
        )[:100]
    )

    best_similarity = 0.0
    best_complaint_id = None
    best_comparison = None

    for previous in complaints:
        previous_description = (
            normalize_complaint_text(
                previous.description
            )
        )

        previous_combined = (
            _combined_content(
                previous.title,
                previous.description,
            )
        )

        previous_compact_description = (
            compact_complaint_text(
                previous.description
            )
        )

        previous_compact_combined = (
            compact_complaint_text(
                f"{previous.title} "
                f"{previous.description}"
            )
        )

        if not previous_description:
            continue

        if (
            previous_description
            == current_description
        ):
            return {
                "type": "duplicate",
                "complaint_id": previous.pk,
                "similarity": 1.0,
                "comparison": "description",
            }

        if (
            previous_compact_description
            == current_compact_description
        ):
            return {
                "type": "duplicate",
                "complaint_id": previous.pk,
                "similarity": 1.0,
                "comparison": "compact_description",
            }

        if (
            previous_combined
            == current_combined
        ):
            return {
                "type": "duplicate",
                "complaint_id": previous.pk,
                "similarity": 1.0,
                "comparison": "combined",
            }

        if (
            previous_compact_combined
            == current_compact_combined
        ):
            return {
                "type": "duplicate",
                "complaint_id": previous.pk,
                "similarity": 1.0,
                "comparison": "compact_combined",
            }

        description_similarity = (
            SequenceMatcher(
                None,
                current_description,
                previous_description,
                autojunk=False,
            ).ratio()
        )

        compact_description_similarity = (
            SequenceMatcher(
                None,
                current_compact_description,
                previous_compact_description,
                autojunk=False,
            ).ratio()
        )

        combined_similarity = (
            SequenceMatcher(
                None,
                current_combined,
                previous_combined,
                autojunk=False,
            ).ratio()
        )

        compact_combined_similarity = (
            SequenceMatcher(
                None,
                current_compact_combined,
                previous_compact_combined,
                autojunk=False,
            ).ratio()
        )

        similarity_candidates = {
            "description":
                description_similarity,
            "compact_description":
                compact_description_similarity,
            "combined":
                combined_similarity,
            "compact_combined":
                compact_combined_similarity,
        }

        best_type = max(
            similarity_candidates,
            key=similarity_candidates.get,
        )

        candidate_similarity = (
            similarity_candidates[
                best_type
            ]
        )

        if (
            candidate_similarity
            >= SIMILARITY_THRESHOLD
        ):
            return {
                "type": "similar",
                "complaint_id": previous.pk,
                "similarity": (
                    candidate_similarity
                ),
                "comparison": best_type,
            }

        if (
            candidate_similarity
            > best_similarity
        ):
            best_similarity = (
                candidate_similarity
            )

            best_complaint_id = (
                previous.pk
            )

            best_comparison = (
                best_type
            )

    if best_complaint_id:
        return {
            "type": "different",
            "complaint_id": (
                best_complaint_id
            ),
            "similarity": (
                best_similarity
            ),
            "comparison": (
                best_comparison
            ),
        }

    return None


def check_complaint_submission(
    *,
    request,
    user,
    company,
    title,
    description,
):
    now = timezone.now()

    if not user.is_verified:
        return _block(
            request=request,
            event_type=(
                AbuseAttempt.EventType.UNVERIFIED_ACCOUNT
            ),
            message=(
                "E-posta adresinizi doğrulamadan "
                "şikayet oluşturamazsınız."
            ),
            detail=(
                "Doğrulanmamış kullanıcı şikayet "
                "oluşturmaya çalıştı."
            ),
            metadata={
                "user_id": user.pk,
            },
        )

    fill_seconds = (
        _form_fill_seconds(
            request
        )
    )

    if fill_seconds is None:
        mark_complaint_form_opened(
            request
        )

        return _block(
            request=request,
            event_type=(
                AbuseAttempt.EventType.FORM_TOO_FAST
            ),
            message=(
                "Şikayet formu doğrulanamadı. "
                "Lütfen sayfayı yenileyip tekrar deneyin."
            ),
            detail=(
                "Form açılış zaman damgası olmadan "
                "şikayet gönderme denemesi yapıldı."
            ),
            metadata={
                "reason":
                    "missing_form_timestamp",
            },
        )

    if (
        fill_seconds
        < MIN_FORM_FILL_SECONDS
    ):
        mark_complaint_form_opened(
            request
        )

        return _block(
            request=request,
            event_type=(
                AbuseAttempt.EventType.FORM_TOO_FAST
            ),
            message=(
                "Form olağandışı hızlı gönderildi. "
                "Lütfen kısa bir süre bekleyip "
                "tekrar deneyin."
            ),
            detail=(
                "Şikayet formu minimum doldurma "
                "süresinden daha hızlı gönderildi."
            ),
            metadata={
                "fill_seconds": round(
                    fill_seconds,
                    3,
                ),
                "minimum_seconds":
                    MIN_FORM_FILL_SECONDS,
            },
        )

    similar = (
        _find_duplicate_or_similar_complaint(
            user=user,
            company=company,
            title=title,
            description=description,
        )
    )

    if (
        similar
        and similar["type"]
        == "duplicate"
    ):
        return _block(
            request=request,
            event_type=(
                AbuseAttempt.EventType.DUPLICATE_COMPLAINT
            ),
            message=(
                "Bu şikayetin aynısını daha önce "
                "gönderdiniz."
            ),
            detail=(
                "Normalize edilmiş şikayet içeriği "
                "önceki bir şikayetle tamamen eşleşti."
            ),
            metadata={
                "matched_complaint_id": (
                    similar[
                        "complaint_id"
                    ]
                ),
                "similarity": 1.0,
                "comparison": (
                    similar.get(
                        "comparison"
                    )
                ),
                "company_id":
                    company.pk,
            },
        )

    if (
        similar
        and similar["type"]
        == "similar"
    ):
        similarity_percent = round(
            similar["similarity"]
            * 100,
            1,
        )

        return _block(
            request=request,
            event_type=(
                AbuseAttempt.EventType.SIMILAR_COMPLAINT
            ),
            message=(
                "Bu şikayet aynı şirkete daha önce "
                "gönderdiğiniz bir içerikle çok "
                "benzer görünüyor."
            ),
            detail=(
                "Yeni şikayet önceki bir şikayetle "
                f"%{similarity_percent} benzer bulundu."
            ),
            metadata={
                "matched_complaint_id": (
                    similar[
                        "complaint_id"
                    ]
                ),
                "similarity": round(
                    similar[
                        "similarity"
                    ],
                    4,
                ),
                "threshold":
                    SIMILARITY_THRESHOLD,
                "comparison": (
                    similar.get(
                        "comparison"
                    )
                ),
                "company_id":
                    company.pk,
            },
        )

    open_count = (
        Complaint.objects
        .filter(
            user=user,
            status__in=(
                Complaint.Status.PENDING,
                Complaint.Status.PUBLISHED,
            ),
            withdrawn_at__isnull=True,
        )
        .count()
    )

    if (
        open_count
        >= MAX_OPEN_COMPLAINTS
    ):
        return _block(
            request=request,
            event_type=(
                AbuseAttempt.EventType.OPEN_COMPLAINT_LIMIT
            ),
            message=(
                "Aynı anda en fazla "
                f"{MAX_OPEN_COMPLAINTS} açık "
                "şikayetiniz bulunabilir. "
                "Mevcut şikayetlerinizden bazıları "
                "sonuçlandıktan sonra tekrar deneyin."
            ),
            detail=(
                "Kullanıcı açık şikayet "
                "sınırına ulaştı."
            ),
            metadata={
                "open_complaint_count":
                    open_count,
                "limit":
                    MAX_OPEN_COMPLAINTS,
            },
        )

    restriction = (
        _rejection_restriction(
            user,
            now,
        )
    )

    if restriction["active"]:
        complaints_last_24h = (
            Complaint.objects
            .filter(
                user=user,
                created_at__gte=(
                    now
                    - timedelta(
                        hours=24
                    )
                ),
            )
            .count()
        )

        if (
            complaints_last_24h
            >= REJECTION_RESTRICTED_MAX_24_HOURS
        ):
            return _block(
                request=request,
                event_type=(
                    AbuseAttempt.EventType.REJECTION_RESTRICTION
                ),
                message=(
                    "Son dönemde birden fazla "
                    "şikayetiniz moderasyon tarafından "
                    "reddedildiği için hesabınız geçici "
                    "olarak sıkı gönderim limitine "
                    "alınmıştır. Bu süre içinde "
                    "24 saatte en fazla 1 şikayet "
                    "oluşturabilirsiniz."
                ),
                detail=(
                    "Kullanıcı reddedilme geçmişi "
                    "nedeniyle 3 günlük sıkı limite "
                    "takıldı."
                ),
                metadata={
                    "rejected_last_10_days": (
                        restriction[
                            "rejected_count"
                        ]
                    ),
                    "restriction_until": (
                        restriction[
                            "until"
                        ].isoformat()
                        if restriction[
                            "until"
                        ]
                        else None
                    ),
                    "complaints_last_24h":
                        complaints_last_24h,
                    "daily_limit":
                        REJECTION_RESTRICTED_MAX_24_HOURS,
                },
            )

    account_age = (
        now
        - user.date_joined
    )

    if (
        account_age
        < timedelta(
            hours=NEW_ACCOUNT_AGE_HOURS
        )
    ):
        new_account_count = (
            Complaint.objects
            .filter(
                user=user,
                created_at__gte=(
                    now
                    - timedelta(
                        hours=24
                    )
                ),
            )
            .count()
        )

        if (
            new_account_count
            >= NEW_ACCOUNT_MAX_24_HOURS
        ):
            return _block(
                request=request,
                event_type=(
                    AbuseAttempt.EventType.NEW_ACCOUNT_LIMIT
                ),
                message=(
                    "Yeni hesaplar ilk 24 saat içinde "
                    "en fazla 2 şikayet oluşturabilir."
                ),
                detail=(
                    "İlk 24 saat içindeki kullanıcı "
                    "yeni hesap gönderim limitine ulaştı."
                ),
                metadata={
                    "complaints_last_24h":
                        new_account_count,
                    "limit":
                        NEW_ACCOUNT_MAX_24_HOURS,
                    "account_age_seconds": (
                        int(
                            account_age
                            .total_seconds()
                        )
                    ),
                },
            )

    ten_minutes_ago = (
        now
        - timedelta(
            minutes=10
        )
    )

    count_10m = (
        Complaint.objects
        .filter(
            user=user,
            created_at__gte=ten_minutes_ago,
        )
        .count()
    )

    if (
        count_10m
        >= MAX_COMPLAINTS_10_MINUTES
    ):
        return _block(
            request=request,
            event_type=(
                AbuseAttempt.EventType.COMPLAINT_RATE_LIMIT_10M
            ),
            message=(
                "10 dakika içinde en fazla "
                "2 şikayet oluşturabilirsiniz. "
                "Lütfen daha sonra tekrar deneyin."
            ),
            detail=(
                "Kullanıcı 10 dakikalık şikayet "
                "oluşturma limitine ulaştı."
            ),
            metadata={
                "complaints_last_10m":
                    count_10m,
                "limit":
                    MAX_COMPLAINTS_10_MINUTES,
            },
        )

    one_hour_ago = (
        now
        - timedelta(
            hours=1
        )
    )

    count_1h = (
        Complaint.objects
        .filter(
            user=user,
            created_at__gte=one_hour_ago,
        )
        .count()
    )

    if (
        count_1h
        >= MAX_COMPLAINTS_1_HOUR
    ):
        return _block(
            request=request,
            event_type=(
                AbuseAttempt.EventType.COMPLAINT_RATE_LIMIT_1H
            ),
            message=(
                "1 saat içinde en fazla "
                "3 şikayet oluşturabilirsiniz. "
                "Lütfen daha sonra tekrar deneyin."
            ),
            detail=(
                "Kullanıcı 1 saatlik şikayet "
                "oluşturma limitine ulaştı."
            ),
            metadata={
                "complaints_last_1h":
                    count_1h,
                "limit":
                    MAX_COMPLAINTS_1_HOUR,
            },
        )

    twenty_four_hours_ago = (
        now
        - timedelta(
            hours=24
        )
    )

    count_24h = (
        Complaint.objects
        .filter(
            user=user,
            created_at__gte=(
                twenty_four_hours_ago
            ),
        )
        .count()
    )

    if (
        count_24h
        >= MAX_COMPLAINTS_24_HOURS
    ):
        return _block(
            request=request,
            event_type=(
                AbuseAttempt.EventType.COMPLAINT_RATE_LIMIT_24H
            ),
            message=(
                "24 saat içinde en fazla "
                "5 şikayet oluşturabilirsiniz. "
                "Lütfen daha sonra tekrar deneyin."
            ),
            detail=(
                "Kullanıcı 24 saatlik şikayet "
                "oluşturma limitine ulaştı."
            ),
            metadata={
                "complaints_last_24h":
                    count_24h,
                "limit":
                    MAX_COMPLAINTS_24_HOURS,
            },
        )

    company_cooldown_start = (
        now
        - timedelta(
            minutes=(
                SAME_COMPANY_COOLDOWN_MINUTES
            )
        )
    )

    last_company_complaint = (
        Complaint.objects
        .filter(
            user=user,
            company=company,
            created_at__gte=(
                company_cooldown_start
            ),
        )
        .order_by(
            "-created_at",
            "-pk",
        )
        .first()
    )

    if last_company_complaint:
        next_allowed_at = (
            last_company_complaint.created_at
            + timedelta(
                minutes=(
                    SAME_COMPANY_COOLDOWN_MINUTES
                )
            )
        )

        remaining_seconds = max(
            0,
            int(
                (
                    next_allowed_at
                    - now
                ).total_seconds()
            ),
        )

        remaining_minutes = max(
            1,
            (
                remaining_seconds
                + 59
            )
            // 60,
        )

        return _block(
            request=request,
            event_type=(
                AbuseAttempt.EventType.SAME_COMPANY_COOLDOWN
            ),
            message=(
                "Bu şirket için kısa süre önce "
                "bir şikayet oluşturdunuz. "
                "Yeni bir şikayet oluşturmak için "
                f"yaklaşık {remaining_minutes} "
                "dakika bekleyin."
            ),
            detail=(
                "Kullanıcı aynı şirkete uygulanan "
                "30 dakikalık cooldown süresine "
                "takıldı."
            ),
            metadata={
                "company_id":
                    company.pk,
                "company_name":
                    company.name,
                "previous_complaint_id": (
                    last_company_complaint.pk
                ),
                "next_allowed_at": (
                    next_allowed_at
                    .isoformat()
                ),
                "remaining_seconds":
                    remaining_seconds,
            },
        )

    return _allow()