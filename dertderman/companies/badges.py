from dataclasses import dataclass

from django.db.models import DateTimeField, OuterRef, Subquery
from django.db.models.functions import Coalesce

from complaints.models import Complaint, ComplaintEvent

from .models import Company, CompanyResponse


@dataclass(frozen=True)
class CompanyBadge:
    key: str
    name: str
    description: str
    priority: int


BADGES = {
    "company-new-member": CompanyBadge("company-new-member", "Yeni Kurumsal Üye", "Onaylı ve doğrulanmış şirket hesabı DertDerman'a katıldı.", 10),
    "company-first-response": CompanyBadge("company-first-response", "İlk Yanıt", "İlk resmi yanıtını public bir şikayette paylaştı.", 20),
    "company-active-responder": CompanyBadge("company-active-responder", "Aktif Yanıt Veren", "En az 10 farklı public şikayete resmi yanıt verdi.", 40),
    "company-fast-response": CompanyBadge("company-fast-response", "Hızlı Yanıt", "En az 5 yanıtlık örneklemde ortalama ilk yanıt süresi 24 saatin altında.", 55),
    "company-high-response": CompanyBadge("company-high-response", "Yüksek Cevap Oranı", "En az 10 public şikayette yüzde 80 veya üzeri cevap oranına ulaştı.", 60),
    "company-solution-focused": CompanyBadge("company-solution-focused", "Çözüm Odaklı Şirket", "En az 5 public şikayet çözümle sonuçlandı.", 50),
    "company-high-resolution": CompanyBadge("company-high-resolution", "Yüksek Çözüm Oranı", "En az 10 public şikayette yüzde 60 veya üzeri çözüm oranına ulaştı.", 70),
    "company-active-account": CompanyBadge("company-active-account", "Aktif Kurumsal Hesap", "En az 15 farklı şikayete, en az 5 ayrı günde resmi yanıt verdi.", 45),
    "company-consistent-resolution": CompanyBadge("company-consistent-resolution", "İstikrarlı Çözüm", "En az 90 güne yayılan yeterli örneklemde güçlü cevap ve çözüm performansı gösterdi.", 80),
    "company-trust": CompanyBadge("company-trust", "DertDerman Güven Rozeti", "Yeterli örneklemde doğrulanmış, hızlı ve yüksek cevap/çözüm performansı gösterdi.", 100),
}


def company_badge_facts(company_ids):
    company_ids = tuple({company_id for company_id in company_ids if company_id})
    if not company_ids:
        return {}
    facts = {
        company_id: {
            "approved": False, "verified": False, "total": 0, "answered": 0,
            "resolved": 0, "response_seconds": [], "response_days": set(),
            "first_response": None, "last_response": None,
        }
        for company_id in company_ids
    }
    for row in Company.objects.filter(pk__in=company_ids).values(
        "pk", "is_active", "is_verified", "approval_status", "archived_at",
    ):
        facts[row["pk"]]["approved"] = (
            row["is_active"] and row["is_verified"]
            and row["approval_status"] == Company.ApprovalStatus.APPROVED
            and row["archived_at"] is None
        )

    first_response = CompanyResponse.objects.filter(
        complaint_id=OuterRef("pk"), company_id=OuterRef("company_id"), is_active=True,
    ).order_by("created_at", "pk")
    published_event = ComplaintEvent.objects.filter(
        complaint_id=OuterRef("pk"), event_type=ComplaintEvent.Type.PUBLISHED,
    ).order_by("occurred_at", "pk")
    rows = Complaint.objects.filter(
        company_id__in=company_ids,
        status__in=(Complaint.Status.PUBLISHED, Complaint.Status.RESOLVED),
        withdrawn_at__isnull=True,
    ).annotate(
        first_response_at=Subquery(first_response.values("created_at")[:1], output_field=DateTimeField()),
        published_at=Coalesce(
            Subquery(published_event.values("occurred_at")[:1], output_field=DateTimeField()),
            "created_at",
        ),
    ).values_list("company_id", "status", "created_at", "published_at", "first_response_at")

    for company_id, status, created_at, published_at, first_response_at in rows:
        data = facts[company_id]
        data["total"] += 1
        data["resolved"] += status == Complaint.Status.RESOLVED
        if first_response_at is None:
            continue
        data["answered"] += 1
        data["response_days"].add(first_response_at.date())
        data["first_response"] = min(data["first_response"] or first_response_at, first_response_at)
        data["last_response"] = max(data["last_response"] or first_response_at, first_response_at)
        started_at = published_at if first_response_at >= published_at else created_at
        if first_response_at >= started_at:
            data["response_seconds"].append((first_response_at - started_at).total_seconds())
    return facts


def _resolve(data):
    total, answered, resolved = data["total"], data["answered"], data["resolved"]
    response_ratio = answered * 100 / total if total else 0
    resolved_ratio = resolved * 100 / total if total else 0
    average = data.get("average_response_seconds")
    if average is None and data.get("response_seconds"):
        average = sum(data["response_seconds"]) / len(data["response_seconds"])
    span_days = data.get("response_span_days")
    if span_days is None:
        span_days = (
            (data["last_response"] - data["first_response"]).days
            if data["first_response"] and data["last_response"] else 0
        )
    activity_days = data.get("response_activity_days", len(data.get("response_days", ())))
    earned = []
    if data["approved"]:
        earned.append(BADGES["company-new-member"])
    if answered >= 1:
        earned.append(BADGES["company-first-response"])
    if answered >= 10:
        earned.append(BADGES["company-active-responder"])
    if answered >= 5 and average is not None and average <= 24 * 3600:
        earned.append(BADGES["company-fast-response"])
    if total >= 10 and response_ratio >= 80:
        earned.append(BADGES["company-high-response"])
    if resolved >= 5:
        earned.append(BADGES["company-solution-focused"])
    if total >= 10 and resolved_ratio >= 60:
        earned.append(BADGES["company-high-resolution"])
    if answered >= 15 and activity_days >= 5:
        earned.append(BADGES["company-active-account"])
    if total >= 20 and span_days >= 90 and response_ratio >= 80 and resolved_ratio >= 50:
        earned.append(BADGES["company-consistent-resolution"])
    if (
        data["approved"] and total >= 25 and response_ratio >= 90 and resolved_ratio >= 70
        and average is not None and average <= 24 * 3600
    ):
        earned.append(BADGES["company-trust"])
    return tuple(sorted(earned, key=lambda badge: badge.priority))


def resolve_badges_for_companies(company_ids):
    return {company_id: _resolve(data) for company_id, data in company_badge_facts(company_ids).items()}


def resolve_company_badges(company):
    return resolve_badges_for_companies((company.pk,)).get(company.pk, ())


def resolve_company_badges_from_performance(company, performance):
    data = {
        **performance,
        "approved": (
            company.is_active and company.is_verified
            and company.approval_status == Company.ApprovalStatus.APPROVED
            and company.archived_at is None
        ),
    }
    return _resolve(data)


def primary_company_badge(badges):
    return max(badges, key=lambda badge: badge.priority, default=None)
