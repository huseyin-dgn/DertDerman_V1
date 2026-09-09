from django.db.models.signals import post_save
from django.dispatch import receiver
from companies.models import Company, CompanyResponse
from .services import send, send_admins


@receiver(post_save, sender=CompanyResponse)
def response_created(sender, instance, created, raw=False, **kwargs):
    if raw or not created or not instance.is_active or instance.company_id != instance.complaint.company_id:
        return
    send(recipient=instance.complaint.user, scope='USER', kind='RESPONSE',
         event_key=f'response:{instance.pk}', title='Şirket şikayetinize cevap verdi.',
         message='Şirket yanıtını şikayetinizin detayında inceleyebilirsiniz.',
         complaint=instance.complaint, company=instance.company)


@receiver(post_save, sender=Company)
def application_created(sender, instance, created, raw=False, **kwargs):
    if not raw and created and instance.approval_status == 'PENDING':
        send_admins(kind='APPLICATION', event_key=f'application:{instance.pk}',
                    title='Yeni şirket başvurusu.', message=instance.name, company=instance)
