from django.conf import settings
from django.db import models
from django.urls import reverse


class Notification(models.Model):
    class Scope(models.TextChoices):
        USER = 'USER', 'Bireysel'
        ADMIN = 'ADMIN', 'Yönetim'

    class Type(models.TextChoices):
        CREATED = "CREATED", "Şikayet oluşturuldu"
        PENDING = "PENDING", "İncelemeye alındı"
        PUBLISHED = "PUBLISHED", "Yayınlandı"
        COMPANY_RESPONDED = "COMPANY_RESPONDED", "Şirket cevapladı"
        RESOLVED = "RESOLVED", "Çözüldü"
        REJECTED = "REJECTED", "Reddedildi"
        REMOVED = "REMOVED", "İhlal nedeniyle kaldırıldı"
        EDITED = "EDITED", "Kullanıcı tarafından düzenlendi"
        WITHDRAWN = "WITHDRAWN", "Geri çekildi"
        CONTENT_REPORT = "CONTENT_REPORT", "İçerik raporu"
        USER_REPORT = "USER_REPORT", "Kullanıcı raporu"
        ABUSE_ALERT = "ABUSE_ALERT", "Güvenlik olayı"

    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )

    recipient_role = models.CharField(
        max_length=10,
        choices=Scope.choices
    )

    company = models.ForeignKey(
        'companies.Company',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    complaint = models.ForeignKey(
        'complaints.Complaint',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    content_report = models.ForeignKey(
        'complaints.ContentReport',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='admin_notifications',
    )

    user_report = models.ForeignKey(
        'complaints.UserReport',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='admin_notifications',
    )

    abuse_attempt = models.ForeignKey(
        'core.AbuseAttempt',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='admin_notifications',
    )

    notification_type = models.CharField(
        max_length=20,
        choices=Type.choices
    )

    title = models.CharField(
        max_length=180
    )

    message = models.TextField(
        blank=True
    )

    event_key = models.CharField(
        max_length=180
    )

    is_read = models.BooleanField(
        default=False
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    read_at = models.DateTimeField(
        null=True,
        blank=True
    )

    class Meta:
        ordering = (
            'is_read',
            '-created_at',
            '-pk'
        )

        indexes = [
            models.Index(
                fields=[
                    'recipient_user',
                    'recipient_role',
                    'is_read',
                    '-created_at'
                ],
                name='notification_inbox'
            )
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    'recipient_user',
                    'recipient_role',
                    'event_key'
                ],
                name='notification_recipient_event'
            )
        ]

    @property
    def target_url(self):
        # No URL from request data or stored free-form URL is ever followed.

        if (
            self.abuse_attempt_id
            and self.recipient_role == self.Scope.ADMIN
        ):
            return reverse(
                'adminx:security_event_detail',
                args=[self.abuse_attempt_id]
            )

        if self.content_report_id:
            return reverse(
                'adminx:report_detail',
                args=[self.content_report_id]
            )

        if self.user_report_id:
            return reverse(
                'adminx:user_report_detail',
                args=[self.user_report_id]
            )

        if self.complaint_id:
            route = (
                'adminx:complaint_detail'
                if self.recipient_role == self.Scope.ADMIN
                else 'complaints:detail'
            )

            return reverse(
                route,
                args=[self.complaint_id]
            )

        if self.company_id and self.recipient_role == self.Scope.ADMIN:
            return reverse(
                'adminx:company_application_detail',
                args=[self.company_id]
            )

        return reverse(
            'adminx:notifications'
            if self.recipient_role == self.Scope.ADMIN
            else 'notifications:list'
        )

    @property
    def icon(self):
        return {
            'RESPONSE': 'reply',
            'RESOLVED': 'check',
            'APPLICATION': 'building',
            'REJECTED': 'shield',
            'MODERATION': 'clock',
            'LIKE': 'check',
            'REACTION': 'bell',
            'COMMENT': 'reply',
            'CONTENT_REPORT': 'shield',
            'USER_REPORT': 'shield',
            'ABUSE_ALERT': 'shield',
        }.get(
            self.notification_type,
            'bell'
        )