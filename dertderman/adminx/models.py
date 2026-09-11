from django.conf import settings
from django.db import models


class AdminAuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "CREATE", "Oluşturma"
        UPDATE = "UPDATE", "Güncelleme"
        DELETE = "DELETE", "Silme"
        PUBLISH = "PUBLISH", "Yayınlama"
        REJECT = "REJECT", "Reddetme"
        RESOLVE = "RESOLVE", "Çözüldü olarak işaretleme"
        ARCHIVE = "ARCHIVE", "Arşivleme"
        RESTORE = "RESTORE", "Geri yükleme"
        SUSPEND = "SUSPEND", "Kısıtlama"
        OTHER = "OTHER", "Diğer"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admin_audit_logs",
    )

    action = models.CharField(
        max_length=20,
        choices=Action.choices,
    )

    target_type = models.CharField(
        max_length=100,
        help_text="İşlem yapılan nesnenin türü. Örn: complaint, user, company.",
    )

    target_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="İşlem yapılan nesnenin kimliği.",
    )

    target_label = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="İşlem yapılan nesnenin okunabilir adı.",
    )

    description = models.TextField(
        blank=True,
        default="",
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(
                fields=("actor", "-created_at"),
                name="admin_audit_actor_time",
            ),
            models.Index(
                fields=("target_type", "target_id"),
                name="admin_audit_target",
            ),
            models.Index(
                fields=("action", "-created_at"),
                name="admin_audit_action_time",
            ),
        ]

    def __str__(self):
        actor = self.actor.username if self.actor else "Sistem"
        target = self.target_label or self.target_id or self.target_type
        return f"{actor} · {self.get_action_display()} · {target}"