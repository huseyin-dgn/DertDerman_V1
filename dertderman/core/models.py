from django.conf import settings
from django.db import models


class ContactRequest(models.Model):
    class RequestType(models.TextChoices):
        GENERAL = "GENERAL", "Genel İletişim"
        TECHNICAL = "TECHNICAL", "Teknik Destek"
        COMPANY = "COMPANY", "Şirket / Marka Talebi"
        COMPLAINT = "COMPLAINT", "Şikayetle İlgili Destek"
        OTHER = "OTHER", "Diğer"

    class Status(models.TextChoices):
        NEW = "NEW", "Yeni"
        READ = "READ", "Okundu"
        CLOSED = "CLOSED", "Kapalı"

    name = models.CharField(
        max_length=120
    )

    email = models.EmailField(
        max_length=254
    )

    request_type = models.CharField(
        max_length=20,
        choices=RequestType.choices
    )

    subject = models.CharField(
        max_length=180
    )

    message = models.TextField(
        max_length=4000
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True
    )

    class Meta:
        ordering = (
            "-created_at",
            "-pk"
        )

    def __str__(self):
        return self.subject


class AbuseAttempt(models.Model):
    class EventType(models.TextChoices):
        COMPLAINT_RATE_LIMIT_10M = (
            "COMPLAINT_RATE_LIMIT_10M",
            "10 dakikalık şikayet limiti"
        )

        COMPLAINT_RATE_LIMIT_1H = (
            "COMPLAINT_RATE_LIMIT_1H",
            "1 saatlik şikayet limiti"
        )

        COMPLAINT_RATE_LIMIT_24H = (
            "COMPLAINT_RATE_LIMIT_24H",
            "24 saatlik şikayet limiti"
        )

        NEW_ACCOUNT_LIMIT = (
            "NEW_ACCOUNT_LIMIT",
            "Yeni hesap şikayet limiti"
        )

        UNVERIFIED_ACCOUNT = (
            "UNVERIFIED_ACCOUNT",
            "Doğrulanmamış hesap"
        )

        SAME_COMPANY_COOLDOWN = (
            "SAME_COMPANY_COOLDOWN",
            "Aynı şirkete cooldown"
        )

        DUPLICATE_COMPLAINT = (
            "DUPLICATE_COMPLAINT",
            "Aynı şikayeti tekrar gönderme"
        )

        SIMILAR_COMPLAINT = (
            "SIMILAR_COMPLAINT",
            "Benzer şikayet gönderme"
        )

        FORM_TOO_FAST = (
            "FORM_TOO_FAST",
            "Form olağandışı hızlı gönderildi"
        )

        OPEN_COMPLAINT_LIMIT = (
            "OPEN_COMPLAINT_LIMIT",
            "Açık şikayet limiti"
        )

        REJECTION_RESTRICTION = (
            "REJECTION_RESTRICTION",
            "Reddedilme geçmişi kısıtı"
        )

        ACCOUNT_CREATION_LIMIT = (
            "ACCOUNT_CREATION_LIMIT",
            "IP hesap oluşturma limiti"
        )

        IP_ABUSE_BLOCK = (
            "IP_ABUSE_BLOCK",
            "IP kötüye kullanım engeli"
        )

        OTHER = (
            "OTHER",
            "Diğer"
        )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="abuse_attempts",
    )

    event_type = models.CharField(
        max_length=40,
        choices=EventType.choices,
        db_index=True,
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        db_index=True,
    )

    path = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    method = models.CharField(
        max_length=10,
        blank=True,
        default="",
    )

    detail = models.TextField(
        blank=True,
        default="",
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        ordering = (
            "-created_at",
            "-pk",
        )

        indexes = [
            models.Index(
                fields=(
                    "user",
                    "-created_at",
                ),
                name="abuse_user_recent",
            ),

            models.Index(
                fields=(
                    "ip_address",
                    "-created_at",
                ),
                name="abuse_ip_recent",
            ),

            models.Index(
                fields=(
                    "event_type",
                    "-created_at",
                ),
                name="abuse_event_recent",
            ),
        ]

    def __str__(self):
        if self.user_id:
            return (
                f"@{self.user.username} - "
                f"{self.get_event_type_display()}"
            )

        if self.ip_address:
            return (
                f"{self.ip_address} - "
                f"{self.get_event_type_display()}"
            )

        return self.get_event_type_display()


class IPRiskLog(models.Model):
    class Status(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        SUSPICIOUS = "SUSPICIOUS", "Şüpheli"
        BLOCKED = "BLOCKED", "Engelli"

    ip_address = models.GenericIPAddressField(
        unique=True,
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.NORMAL,
        db_index=True,
    )

    account_count_24h = models.PositiveIntegerField(
        default=0,
    )

    spam_attempt_count = models.PositiveIntegerField(
        default=0,
    )

    rate_limit_count = models.PositiveIntegerField(
        default=0,
    )

    first_account_created_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    last_account_created_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    block_reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    blocked_until = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = (
            "-updated_at",
            "-pk",
        )

        indexes = [
            models.Index(
                fields=(
                    "status",
                    "-updated_at",
                ),
                name="ip_risk_status",
            ),
        ]

    def __str__(self):
        return (
            f"{self.ip_address} - "
            f"{self.get_status_display()}"
        )