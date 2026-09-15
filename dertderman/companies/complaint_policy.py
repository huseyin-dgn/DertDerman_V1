from complaints.models import Complaint


COMPANY_VISIBLE_COMPLAINT_STATUSES = (
    Complaint.Status.PUBLISHED,
    Complaint.Status.RESOLVED,
    Complaint.Status.REMOVED,
)


COMPANY_PUBLIC_COMPLAINT_STATUSES = (
    Complaint.Status.PUBLISHED,
    Complaint.Status.RESOLVED,
)


def company_can_interact_with_complaint(complaint):
    """
    Şirket yalnızca aktif olarak yayında olan
    bir şikayet üzerinde yeni cevap/not üretebilir.
    """
    return (
        complaint.status == Complaint.Status.PUBLISHED
        and complaint.withdrawn_at is None
        and not complaint.removed_for_violation
        and complaint.violation_removed_at is None
    )


def company_complaint_has_public_page(complaint):
    """
    Public tarafta erişilebilir durumda olan
    şikayet için public sayfa linki gösterilir.
    """
    return (
        complaint.status in COMPANY_PUBLIC_COMPLAINT_STATUSES
        and complaint.withdrawn_at is None
        and not complaint.removed_for_violation
        and complaint.violation_removed_at is None
    )


def company_interaction_lock_reason(complaint):
    if complaint.withdrawn_at is not None:
        return (
            "Bu şikayet kullanıcı tarafından geri çekildi. "
            "Kayıt geçmiş amacıyla görüntülenebilir ancak "
            "yeni şirket cevabı veya dahili not eklenemez."
        )

    if complaint.status == Complaint.Status.RESOLVED:
        return (
            "Bu şikayet çözüldü olarak işaretlendi. "
            "Mevcut cevap ve notlar görüntülenebilir ancak "
            "yeni bir etkileşim başlatılamaz."
        )

    if (
        complaint.status == Complaint.Status.REMOVED
        or complaint.removed_for_violation
        or complaint.violation_removed_at is not None
    ):
        return (
            "Bu şikayet moderasyon nedeniyle yayından "
            "kaldırıldı. Geçmiş kayıtlar korunur ancak "
            "yeni şirket cevabı veya dahili not eklenemez."
        )

    return (
        "Bu şikayet şu anda şirket etkileşimine "
        "açık değil."
    )
