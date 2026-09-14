import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
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
        COMPANY_REPORT = "COMPANY_REPORT", "Şirket raporu"
        ABUSE_ALERT = "ABUSE_ALERT", "Güvenlik olayı"
        ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED", "Hesap askıya alındı"
        ACCOUNT_RESTORED = "ACCOUNT_RESTORED", "Hesap askısı kaldırıldı"

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

    company_report = models.ForeignKey(
        'complaints.CompanyReport',
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
            if self.recipient_role == self.Scope.ADMIN:
                return reverse(
                    'adminx:report_detail',
                    args=[self.content_report_id]
                )

            report = self.content_report
            complaint = report.complaint

            if complaint is None and report.comment_id:
                complaint = report.comment.complaint

            if (
                complaint is not None
                and complaint.status in ("PUBLISHED", "RESOLVED")
                and complaint.withdrawn_at is None
                and complaint.company.is_active
            ):
                return reverse(
                    'complaints:public_detail',
                    args=[complaint.pk]
                )

            return reverse('notifications:list')

        if self.company_report_id:
            if self.recipient_role == self.Scope.ADMIN:
                return reverse(
                    'adminx:company_report_detail',
                    args=[self.company_report_id]
                )
            return reverse('accounts:profile')

        if self.user_report_id:
            if self.recipient_role == self.Scope.ADMIN:
                return reverse(
                    'adminx:user_report_detail',
                    args=[self.user_report_id]
                )

            return reverse('accounts:profile')

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
            'COMPANY_REPORT': 'shield',
            'ABUSE_ALERT': 'shield',
            'ACCOUNT_SUSPENDED': 'shield',
            'ACCOUNT_RESTORED': 'check',
        }.get(
            self.notification_type,
            'bell'
        )


class EmailOutbox(models.Model):
    """Durable email intent; message bodies and raw recipients are not stored."""

    class Kind(models.TextChoices):
        PASSWORD_RESET = "PASSWORD_RESET", "Şifre sıfırlama"
        NOTIFICATION = "NOTIFICATION", "Bildirim"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Bekliyor"
        PROCESSING = "PROCESSING", "İşleniyor"
        RETRY = "RETRY", "Yeniden denenecek"
        SENT = "SENT", "Gönderildi"
        DEAD = "DEAD", "Kalıcı hata"
        CANCELLED = "CANCELLED", "İptal edildi"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=32, choices=Kind.choices)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="email_outbox_items",
    )
    notification = models.OneToOneField(
        Notification,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="email_outbox_item",
    )
    recipient_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
    )
    request_state_hash = models.CharField(max_length=64, blank=True, default="")
    provider = models.CharField(max_length=32, default="resend")
    provider_idempotency_key = models.CharField(max_length=128, unique=True)
    template_version = models.PositiveSmallIntegerField(default=1)
    token_issued_at = models.DateTimeField(null=True, blank=True)
    payload_hash = models.CharField(max_length=64, blank=True, default="")
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=8)
    available_at = models.DateTimeField(db_index=True)
    first_attempt_at = models.DateTimeField(null=True, blank=True)
    provider_retry_deadline_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    claim_token = models.UUIDField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    last_error_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "pk")
        indexes = [
            models.Index(
                fields=["status", "available_at"],
                name="email_outbox_available",
            ),
            models.Index(
                fields=["status", "lease_expires_at"],
                name="email_outbox_lease",
            ),
            models.Index(
                fields=["kind", "status", "created_at"],
                name="email_outbox_kind_status",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        kind="NOTIFICATION",
                        recipient_user__isnull=False,
                        notification__isnull=False,
                        token_issued_at__isnull=True,
                        request_state_hash="",
                    )
                    & ~Q(recipient_hash="")
                )
                | (
                    Q(
                        kind="PASSWORD_RESET",
                        notification__isnull=True,
                        recipient_user__isnull=False,
                        token_issued_at__isnull=False,
                        expires_at__isnull=False,
                    )
                    & ~Q(recipient_hash="")
                    & ~Q(request_state_hash="")
                )
                | Q(
                    kind="PASSWORD_RESET",
                    notification__isnull=True,
                    recipient_user__isnull=True,
                    recipient_hash="",
                    request_state_hash="",
                    token_issued_at__isnull=True,
                    expires_at__isnull=True,
                ),
                name="email_outbox_recipe",
            ),
            models.CheckConstraint(
                condition=Q(
                    status="PROCESSING",
                    claim_token__isnull=False,
                    claimed_at__isnull=False,
                    lease_expires_at__isnull=False,
                )
                | (
                    ~Q(status="PROCESSING")
                    & Q(
                        claim_token__isnull=True,
                        claimed_at__isnull=True,
                        lease_expires_at__isnull=True,
                    )
                ),
                name="email_outbox_claim_fields",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status__in=("SENT", "DEAD", "CANCELLED"))
                    & Q(completed_at__isnull=False)
                )
                | (
                    ~Q(status__in=("SENT", "DEAD", "CANCELLED"))
                    & Q(completed_at__isnull=True)
                ),
                name="email_outbox_completed",
            ),
            models.CheckConstraint(
                condition=Q(max_attempts__gte=1),
                name="email_outbox_attempts_positive",
            ),
            models.CheckConstraint(
                condition=~Q(provider="") & ~Q(provider_idempotency_key=""),
                name="email_outbox_provider_key",
            ),
        ]


class EmailDelivery(models.Model):
    """
    Kalıcı e-posta teslimat kaydı.

    Raw alıcı adresi, mesaj gövdesi, token veya provider hata payload'ı
    saklanmaz. Idempotency key aynı business event'in fiziksel olarak
    tekrar gönderilmesini engeller.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Bekliyor"
        SENT = "SENT", "Gönderildi"
        FAILED = "FAILED", "Başarısız"
        SKIPPED = "SKIPPED", "Atlandı"

    class ProviderStatus(models.TextChoices):
        SENT = "SENT", "Provider gönderdi"
        DELIVERED = "DELIVERED", "Teslim edildi"
        DELAYED = "DELAYED", "Teslimat gecikti"
        BOUNCED = "BOUNCED", "Geri döndü"
        COMPLAINED = "COMPLAINED", "Spam şikayeti"
        FAILED = "FAILED", "Provider başarısız"
        SUPPRESSED = "SUPPRESSED", "Provider tarafından bastırıldı"

    notification = models.ForeignKey(
        Notification,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_deliveries",
    )

    outbox = models.OneToOneField(
        EmailOutbox,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery",
    )

    provider = models.CharField(max_length=32)

    idempotency_key = models.CharField(
        max_length=128,
        unique=True,
    )

    recipient_hash = models.CharField(
        max_length=64,
        db_index=True,
    )

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )

    provider_message_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
    )

    provider_status = models.CharField(
        max_length=32,
        choices=ProviderStatus.choices,
        blank=True,
        default="",
        db_index=True,
    )

    provider_status_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    attempt_count = models.PositiveIntegerField(default=0)

    last_error_type = models.CharField(
        max_length=128,
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    sent_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = (
            "-created_at",
            "-pk",
        )

        indexes = [
            models.Index(
                fields=[
                    "status",
                    "-created_at",
                ],
                name="email_delivery_status",
            )
        ]


class EmailWebhookEvent(models.Model):
    """Minimal, doğrulanmış provider webhook audit kaydı."""

    class ProcessingResult(models.TextChoices):
        MATCHED = "MATCHED", "Teslimatla eşleşti"
        UNMATCHED = "UNMATCHED", "Teslimat bulunamadı"
        IGNORED = "IGNORED", "Takip edilmeyen event"

    provider = models.CharField(max_length=32, default="resend")
    event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=64, db_index=True)
    provider_message_id = models.CharField(
        max_length=255, blank=True, default="", db_index=True
    )
    delivery = models.ForeignKey(
        EmailDelivery,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="webhook_events",
    )
    processing_result = models.CharField(
        max_length=16,
        choices=ProcessingResult.choices,
        default=ProcessingResult.IGNORED,
        db_index=True,
    )
    event_created_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-received_at", "-pk")
        indexes = [
            models.Index(
                fields=["provider", "provider_message_id", "event_created_at"],
                name="email_webhook_lookup",
            )
        ]
