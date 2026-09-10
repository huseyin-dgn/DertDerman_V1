from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

from complaints.models import Complaint, ComplaintComment, ComplaintReaction


PUBLIC_STATUSES = (Complaint.Status.PUBLISHED, Complaint.Status.RESOLVED)


@dataclass(frozen=True)
class UserBadge:
    key: str
    name: str
    description: str
    priority: int


BADGES = {
    "new-contributor": UserBadge("new-contributor", "Yeni Katılımcı", "İlk public deneyimini paylaştı.", 10),
    "contributor": UserBadge("contributor", "Katılımcı", "En az 5 public deneyim paylaştı.", 20),
    "active-contributor": UserBadge("active-contributor", "Aktif Katılımcı", "En az 10 public deneyim paylaştı.", 40),
    "solution-focused": UserBadge("solution-focused", "Çözüm Odaklı", "En az 3 deneyimi çözüme ulaştı.", 50),
    "community-supporter": UserBadge("community-supporter", "Topluluk Destekçisi", "Yorum ve tepkileriyle topluluğa düzenli katkı sağladı.", 30),
    "long-standing": UserBadge("long-standing", "Uzun Süredir Bizimle", "DertDerman topluluğunda en az bir yılını tamamladı.", 25),
}


def resolve_user_badges(user):
    return resolve_badges_for_users((user.pk,)).get(user.pk, ())


def resolve_badges_for_users(user_ids):
    user_ids = tuple({user_id for user_id in user_ids if user_id})
    if not user_ids:
        return {}
    facts = {user_id: {"public": 0, "resolved": 0, "comments": 0, "reactions": 0, "joined": None} for user_id in user_ids}
    public_rows = Complaint.objects.filter(
        user_id__in=user_ids, status__in=PUBLIC_STATUSES, withdrawn_at__isnull=True,
    ).values("user_id").annotate(
        public=Count("pk"), resolved=Count("pk", filter=Q(status=Complaint.Status.RESOLVED)),
    )
    for row in public_rows:
        facts[row["user_id"]].update(public=row["public"], resolved=row["resolved"])
    contribution_filter = {
        "complaint__status__in": PUBLIC_STATUSES,
        "complaint__withdrawn_at__isnull": True,
    }
    for row in ComplaintComment.objects.filter(
        author_user_id__in=user_ids, is_active=True, **contribution_filter,
    ).values("author_user_id").annotate(total=Count("pk")):
        facts[row["author_user_id"]]["comments"] = row["total"]
    for row in ComplaintReaction.objects.filter(
        user_id__in=user_ids, **contribution_filter,
    ).values("user_id").annotate(total=Count("pk")):
        facts[row["user_id"]]["reactions"] = row["total"]
    for row in get_user_model().objects.filter(pk__in=user_ids).values("pk", "date_joined"):
        facts[row["pk"]]["joined"] = row["date_joined"]

    cutoff = timezone.now() - timedelta(days=365)
    resolved = {}
    for user_id, data in facts.items():
        earned = []
        if data["public"] >= 1:
            earned.append(BADGES["new-contributor"])
        if data["public"] >= 5:
            earned.append(BADGES["contributor"])
        if data["public"] >= 10:
            earned.append(BADGES["active-contributor"])
        if data["resolved"] >= 3:
            earned.append(BADGES["solution-focused"])
        if data["comments"] >= 3 and data["comments"] + data["reactions"] >= 10:
            earned.append(BADGES["community-supporter"])
        if data["joined"] and data["joined"] <= cutoff:
            earned.append(BADGES["long-standing"])
        resolved[user_id] = tuple(sorted(earned, key=lambda badge: badge.priority))
    return resolved


def primary_badge(badges):
    return max(badges, key=lambda badge: badge.priority, default=None)
