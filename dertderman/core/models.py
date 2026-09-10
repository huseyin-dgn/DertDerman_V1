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

    name = models.CharField(max_length=120)
    email = models.EmailField(max_length=254)
    request_type = models.CharField(max_length=20, choices=RequestType.choices)
    subject = models.CharField(max_length=180)
    message = models.TextField(max_length=4000)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW, db_index=True)

    class Meta:
        ordering = ("-created_at", "-pk")

    def __str__(self):
        return self.subject
