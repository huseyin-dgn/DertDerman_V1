from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from complaints.models import Complaint
from .models import Company, CompanyNotification


def record_complaint_notification(complaint, kind):
    return CompanyNotification.objects.create(
        company_id=complaint.company_id, complaint=complaint,
        kind=kind, title=CompanyNotification.Kind(kind).label,
    )


@receiver(pre_save, sender=Complaint)
def capture_complaint_state(sender, instance, raw=False, **kwargs):
    if not raw:
        instance._company_panel_previous = sender.objects.filter(pk=instance.pk).values("status", "title", "description").first() if instance.pk else None


@receiver(post_save, sender=Complaint)
def notify_company_of_complaint(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    previous = getattr(instance, "_company_panel_previous", None)
    kind = None
    if created:
        kind = CompanyNotification.Kind.NEW
    elif previous and previous["status"] != instance.status:
        kind = {
            Complaint.Status.PUBLISHED: CompanyNotification.Kind.PUBLISHED,
            Complaint.Status.RESOLVED: CompanyNotification.Kind.RESOLVED,
        }.get(instance.status, CompanyNotification.Kind.ADMIN)
    elif previous and any(previous[field] != getattr(instance, field) for field in ("title", "description")):
        kind = CompanyNotification.Kind.UPDATED
    if kind:
        record_complaint_notification(instance, kind)


@receiver(pre_save, sender=Company)
def capture_company_state(sender, instance, raw=False, **kwargs):
    if not raw:
        instance._panel_approval_previous = sender.objects.filter(pk=instance.pk).values("approval_status", "is_verified", "is_active").first() if instance.pk else None


@receiver(post_save, sender=Company)
def notify_company_of_admin_action(sender, instance, created, raw=False, **kwargs):
    previous = getattr(instance, "_panel_approval_previous", None)
    if not raw and not created and previous and any(previous[key] != getattr(instance, key) for key in previous):
        CompanyNotification.objects.create(company=instance, kind=CompanyNotification.Kind.ADMIN,
            title="Şirketinizin onay veya doğrulama durumu güncellendi.")
