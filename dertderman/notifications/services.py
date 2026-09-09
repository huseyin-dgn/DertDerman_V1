from django.utils import timezone
from accounts.models import User
from .models import Notification


def send(*, recipient, scope, kind, event_key, title, message='', complaint=None, company=None):
    if not recipient.is_active or recipient.user_type != scope:
        return None
    return Notification.objects.get_or_create(recipient_user=recipient, recipient_role=scope,
        event_key=event_key, defaults={'notification_type': kind, 'title': title, 'message': message,
                                    'complaint': complaint, 'company': None if complaint else company})[0]


def send_admins(**event):
    for admin in User.objects.filter(user_type='ADMIN', is_active=True).iterator():
        send(recipient=admin, scope='ADMIN', **event)


def complaint_event(complaint, kind, event_key):
    mapping = {
        'NEW': ('RECEIVED', 'Şikayetiniz alındı.', 'Şikayetiniz yayınlanmadan önce yönetim tarafından incelenecek.'),
        'PUBLISHED': ('PUBLISHED', 'Şikayetiniz yayınlandı.', 'Şikayetinizin durumunu kişisel alanınızdan takip edebilirsiniz.'),
        'RESOLVED': ('RESOLVED', 'Şikayetiniz çözüldü.', 'Şikayetiniz çözülmüş olarak güncellendi.'),
        'ADMIN': ('REJECTED', 'Şikayetiniz reddedildi.', 'Şikayetinizin yayın başvurusu kabul edilmedi.') if complaint.status == 'REJECTED'
                 else ('UPDATED', 'Şikayetinizin durumu güncellendi.', 'Güncel durumu kişisel alanınızdan inceleyebilirsiniz.'),
    }
    if kind in mapping:
        notification_type, title, message = mapping[kind]
        send(recipient=complaint.user, scope='USER', kind=notification_type, event_key=event_key,
             title=title, message=message, complaint=complaint, company=complaint.company)
    if kind == 'NEW' and complaint.status == 'PENDING':
        send_admins(kind='MODERATION', event_key=event_key, title='Yeni şikayet moderasyon bekliyor.',
                    message=complaint.title, complaint=complaint, company=complaint.company)


def mark_read(queryset):
    return queryset.filter(is_read=False).update(is_read=True, read_at=timezone.now())
