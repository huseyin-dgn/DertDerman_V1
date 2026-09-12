from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from companies.models import Company


class Complaint(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "İncelemede"
        PUBLISHED = "PUBLISHED", "Yayında"
        RESOLVED = "RESOLVED", "Çözüldü"
        REJECTED = "REJECTED", "Reddedildi"
        REMOVED = "REMOVED", "İhlal nedeniyle kaldırıldı"

    class Category(models.TextChoices):
        PRODUCT_SERVICE = (
            "PRODUCT_SERVICE",
            "Ürün / Hizmet Kalitesi",
        )
        DELIVERY = (
            "DELIVERY",
            "Teslimat / Kargo",
        )
        REFUND = (
            "REFUND",
            "İade / Ücret",
        )
        BILLING = (
            "BILLING",
            "Ödeme / Faturalandırma",
        )
        CUSTOMER_SERVICE = (
            "CUSTOMER_SERVICE",
            "Müşteri Hizmetleri",
        )
        ACCOUNT = (
            "ACCOUNT",
            "Hesap / Üyelik",
        )
        TECHNICAL = (
            "TECHNICAL",
            "Teknik Sorun",
        )
        CAMPAIGN_PRICE = (
            "CAMPAIGN_PRICE",
            "Kampanya / Fiyat",
        )
        WARRANTY_SERVICE = (
            "WARRANTY_SERVICE",
            "Garanti / Servis",
        )
        PRIVACY_SECURITY = (
            "PRIVACY_SECURITY",
            "Gizlilik / Güvenlik",
        )
        OTHER = (
            "OTHER",
            "Diğer",
        )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="complaints",
    )

    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="complaints",
    )
    category = models.CharField(
        max_length=32,
        choices=Category.choices,
        default=Category.OTHER,
        db_index=True,
    )

    title = models.CharField(
        max_length=150,
    )

    description = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    view_count = models.PositiveBigIntegerField(
        default=0,
        editable=False,
    )

    withdrawn_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )

    removed_for_violation = models.BooleanField(
        default=False,
        db_index=True,
    )

    violation_removed_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )

    violation_removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="violation_removed_complaints",
    )

    violation_reason = models.CharField(
        max_length=30,
        blank=True,
        default="",
    )

    violation_report = models.ForeignKey(
        "ContentReport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="removed_complaints",
    )

    class Meta:
        ordering = (
            "-created_at",
            "-pk",
        )

        indexes = [
            models.Index(
                fields=(
                    "company",
                    "category",
                    "status",
                    "-created_at",
                ),
                name="compl_pub_cat_recent",
            ),
        ]

    def clean(self):
        errors = {}

        title = self.title.strip() if self.title else ""
        description = self.description.strip() if self.description else ""

        if len(title) < 5:
            errors["title"] = "Başlık en az 5 karakter olmalıdır."

        if len(description) < 20:
            errors["description"] = "Açıklama en az 20 karakter olmalıdır."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title


class ComplaintEvent(models.Model):
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

    class Actor(models.TextChoices):
        SYSTEM = "SYSTEM", "Sistem"
        USER = "USER", "Kullanıcı"
        ADMIN = "ADMIN", "Yönetici"
        COMPANY = "COMPANY", "Şirket"

    complaint = models.ForeignKey(
        Complaint,
        on_delete=models.CASCADE,
        related_name="timeline_events",
    )

    event_type = models.CharField(
        max_length=24,
        choices=Type.choices,
    )

    actor_type = models.CharField(
        max_length=12,
        choices=Actor.choices,
        default=Actor.SYSTEM,
    )

    message = models.CharField(
        max_length=300,
    )

    source_key = models.CharField(
        max_length=180,
        unique=True,
    )

    occurred_at = models.DateTimeField(
        default=timezone.now,
    )

    class Meta:
        ordering = (
            "occurred_at",
            "pk",
        )

        indexes = [
            models.Index(
                fields=(
                    "complaint",
                    "occurred_at",
                ),
                name="complaint_timeline",
            )
        ]

    def __str__(self):
        return f"{self.complaint_id}: {self.event_type}"


class ComplaintLike(models.Model):
    complaint = models.ForeignKey(
        Complaint,
        on_delete=models.CASCADE,
        related_name="likes",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="complaint_likes",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "complaint",
                    "user",
                ),
                name="unique_complaint_like",
            )
        ]

        ordering = (
            "-created_at",
            "-pk",
        )


class ComplaintReaction(models.Model):
    class Type:
        AGREE = "👍"
        SUPPORT = "❤️"
        SURPRISED = "😮"
        SAD = "😕"

    complaint = models.ForeignKey(
        Complaint,
        on_delete=models.CASCADE,
        related_name="reactions",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="complaint_reactions",
    )

    reaction_type = models.CharField(
        max_length=32,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "complaint",
                    "user",
                ),
                name="unique_complaint_reaction",
            )
        ]

        ordering = (
            "-updated_at",
            "-pk",
        )


class ComplaintComment(models.Model):
    complaint = models.ForeignKey(
        Complaint,
        on_delete=models.CASCADE,
        related_name="comments",
    )

    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="complaint_comments",
    )

    body = models.TextField(
        max_length=1000,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = (
            "-created_at",
            "-pk",
        )

        indexes = [
            models.Index(
                fields=(
                    "complaint",
                    "is_active",
                    "-created_at",
                ),
                name="complaint_comment_recent",
            )
        ]

    def clean(self):
        super().clean()

        self.body = (
            self.body or ""
        ).strip()

        if not self.body:
            raise ValidationError(
                {
                    "body": "Yorum boş bırakılamaz.",
                }
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class ContentReport(models.Model):
    class TargetType(models.TextChoices):
        COMPLAINT = "COMPLAINT", "Şikayet"
        COMMENT = "COMMENT", "Yorum"

    class Reason(models.TextChoices):
        SPAM = "SPAM", "Spam / reklam"
        HARASSMENT = "HARASSMENT", "Hakaret / taciz"
        HATE = "HATE", "Nefret söylemi"
        PERSONAL_DATA = "PERSONAL_DATA", "Kişisel veri paylaşımı"
        MISLEADING = "MISLEADING", "Yanıltıcı içerik"
        ILLEGAL = "ILLEGAL", "Yasa dışı içerik"
        OTHER = "OTHER", "Diğer"

    class Status(models.TextChoices):
        PENDING = "PENDING", "İncelenmeyi bekliyor"
        REVIEWING = "REVIEWING", "İnceleniyor"
        RESOLVED = "RESOLVED", "İhlal bulundu"
        REJECTED = "REJECTED", "İhlal bulunmadı"
        ABUSIVE = "ABUSIVE", "Kötü niyetli / asılsız rapor"

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="content_reports",
    )

    target_type = models.CharField(
        max_length=20,
        choices=TargetType.choices,
    )

    complaint = models.ForeignKey(
        Complaint,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reports",
    )

    comment = models.ForeignKey(
        ComplaintComment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reports",
    )

    reason = models.CharField(
        max_length=30,
        choices=Reason.choices,
    )

    description = models.TextField(
        max_length=1000,
        blank=True,
        default="",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_content_reports",
    )

    admin_note = models.TextField(
        max_length=1000,
        blank=True,
        default="",
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = (
            "-created_at",
            "-pk",
        )

        indexes = [
            models.Index(
                fields=(
                    "status",
                    "-created_at",
                ),
                name="content_report_status",
            ),
            models.Index(
                fields=(
                    "target_type",
                    "-created_at",
                ),
                name="content_report_target",
            ),
            models.Index(
                fields=(
                    "reporter",
                    "-created_at",
                ),
                name="content_report_reporter",
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=(
                    "reporter",
                    "complaint",
                ),
                condition=models.Q(
                    complaint__isnull=False,
                ),
                name="unique_user_complaint_report",
            ),
            models.UniqueConstraint(
                fields=(
                    "reporter",
                    "comment",
                ),
                condition=models.Q(
                    comment__isnull=False,
                ),
                name="unique_user_comment_report",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.target_type == self.TargetType.COMPLAINT:
            if not self.complaint:
                errors["complaint"] = (
                    "Şikayet raporu için şikayet seçilmelidir."
                )

            if self.comment:
                errors["comment"] = (
                    "Şikayet raporunda yorum seçilemez."
                )

        elif self.target_type == self.TargetType.COMMENT:
            if not self.comment:
                errors["comment"] = (
                    "Yorum raporu için yorum seçilmelidir."
                )

            if self.complaint:
                errors["complaint"] = (
                    "Yorum raporunda şikayet seçilemez."
                )

        if self.description:
            self.description = self.description.strip()

        if self.admin_note:
            self.admin_note = self.admin_note.strip()

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        target = (
            f"Şikayet #{self.complaint_id}"
            if self.target_type == self.TargetType.COMPLAINT
            else f"Yorum #{self.comment_id}"
        )

        return f"{target} - {self.get_reason_display()}"


class UserReport(models.Model):
    class Reason(models.TextChoices):
        SPAM = "SPAM", "Spam / reklam"
        HARASSMENT = "HARASSMENT", "Hakaret / taciz"
        FAKE_ACCOUNT = "FAKE_ACCOUNT", "Sahte hesap"
        THREAT = "THREAT", "Tehdit"
        PERSONAL_DATA = "PERSONAL_DATA", "Kişisel veri ihlali"
        ABUSE = "ABUSE", "Sistemi kötüye kullanma"
        OTHER = "OTHER", "Diğer"

    class Status(models.TextChoices):
        PENDING = "PENDING", "İncelenmeyi bekliyor"
        REVIEWING = "REVIEWING", "İnceleniyor"
        RESOLVED = "RESOLVED", "İhlal doğrulandı"
        REJECTED = "REJECTED", "İhlal bulunmadı"
        ABUSIVE = "ABUSIVE", "Kötü niyetli / asılsız rapor"

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="submitted_user_reports",
    )

    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_user_reports",
    )

    reason = models.CharField(
        max_length=30,
        choices=Reason.choices,
    )

    description = models.TextField(
        max_length=1000,
        blank=True,
        default="",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_user_reports",
    )

    admin_note = models.TextField(
        max_length=1000,
        blank=True,
        default="",
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = (
            "-created_at",
            "-pk",
        )

        indexes = [
            models.Index(
                fields=(
                    "status",
                    "-created_at",
                ),
                name="user_report_status",
            ),
            models.Index(
                fields=(
                    "reported_user",
                    "-created_at",
                ),
                name="user_report_target",
            ),
        ]

        constraints = [
            models.CheckConstraint(
                condition=~models.Q(
                    reporter=models.F(
                        "reported_user"
                    ),
                ),
                name="user_report_no_self_report",
            ),

            models.UniqueConstraint(
                fields=(
                    "reporter",
                    "reported_user",
                ),
                name="unique_user_report",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.reporter_id
            and self.reported_user_id
            and self.reporter_id
            == self.reported_user_id
        ):
            errors["reported_user"] = (
                "Kullanıcı kendi hesabını raporlayamaz."
            )

        if (
            self.reported_user_id
            and self.reported_user.user_type != "USER"
        ):
            errors["reported_user"] = (
                "Yalnızca bireysel kullanıcı hesapları "
                "raporlanabilir."
            )

        self.description = (
            self.description or ""
        ).strip()

        self.admin_note = (
            self.admin_note or ""
        ).strip()

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"@{self.reporter.username} → "
            f"@{self.reported_user.username}"
        )



class CompanyReport(models.Model):
    class Reason(models.TextChoices):
        FRAUD = "FRAUD", "Dolandırıcılık / sahtecilik şüphesi"
        MISLEADING = "MISLEADING", "Yanıltıcı şirket bilgisi"
        IMPERSONATION = "IMPERSONATION", "Başka şirketi taklit etme"
        ABUSE = "ABUSE", "Sistemi kötüye kullanma"
        ILLEGAL = "ILLEGAL", "Yasa dışı faaliyet / içerik"
        OTHER = "OTHER", "Diğer"

    class Status(models.TextChoices):
        PENDING = "PENDING", "İncelenmeyi bekliyor"
        REVIEWING = "REVIEWING", "İnceleniyor"
        RESOLVED = "RESOLVED", "İhlal doğrulandı"
        REJECTED = "REJECTED", "İhlal bulunmadı"
        ABUSIVE = "ABUSIVE", "Kötü niyetli / asılsız rapor"

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="submitted_company_reports",
    )
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="reports",
    )
    reason = models.CharField(max_length=30, choices=Reason.choices)
    description = models.TextField(max_length=1000, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_company_reports",
    )
    admin_note = models.TextField(max_length=1000, blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(
                fields=("status", "-created_at"),
                name="company_report_status",
            ),
            models.Index(
                fields=("company", "-created_at"),
                name="company_report_target",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("reporter", "company"),
                name="unique_user_company_report",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.reporter_id and self.reporter.user_type != "USER":
            errors["reporter"] = "Yalnızca bireysel kullanıcılar şirket raporu gönderebilir."
        self.description = (self.description or "").strip()
        self.admin_note = (self.admin_note or "").strip()
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"@{self.reporter.username} → {self.company.name}"


class UserViolation(models.Model):
    class SourceType(models.TextChoices):
        COMPLAINT = "COMPLAINT", "Şikayet"
        COMMENT = "COMMENT", "Yorum"
        USER_REPORT = "USER_REPORT", "Kullanıcı raporu"

        FALSE_REPORT = (
            "FALSE_REPORT",
            "Kötü niyetli raporlama",
        )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="violations",
    )

    source_type = models.CharField(
        max_length=20,
        choices=SourceType.choices,
    )

    reason = models.CharField(
        max_length=30,
    )

    description = models.CharField(
        max_length=500,
        blank=True,
        default="",
    )

    content_report = models.ForeignKey(
        "ContentReport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_violations",
    )

    user_report = models.ForeignKey(
        "UserReport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="violations",
    )

    company_report = models.ForeignKey(
        "CompanyReport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="violations",
    )

    complaint = models.ForeignKey(
        Complaint,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_violations",
    )

    comment = models.ForeignKey(
        ComplaintComment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_violations",
    )

    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_user_violations",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
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
                name="user_violation_history",
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=(
                    "content_report",
                ),
                condition=models.Q(
                    content_report__isnull=False,
                ),
                name="unique_content_report_violation",
            ),

            models.UniqueConstraint(
                fields=(
                    "user_report",
                ),
                condition=models.Q(
                    user_report__isnull=False,
                ),
                name="unique_user_report_violation",
            ),

            models.UniqueConstraint(
                fields=(
                    "company_report",
                ),
                condition=models.Q(
                    company_report__isnull=False,
                ),
                name="unique_company_report_violation",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.source_type
            == self.SourceType.COMPLAINT
        ):
            if not self.complaint:
                errors["complaint"] = (
                    "Şikayet ihlali için "
                    "şikayet kaydı gereklidir."
                )

            if not self.content_report:
                errors["content_report"] = (
                    "Şikayet ihlali için "
                    "içerik raporu gereklidir."
                )

        elif (
            self.source_type
            == self.SourceType.COMMENT
        ):
            if not self.comment:
                errors["comment"] = (
                    "Yorum ihlali için "
                    "yorum kaydı gereklidir."
                )

            if not self.content_report:
                errors["content_report"] = (
                    "Yorum ihlali için "
                    "içerik raporu gereklidir."
                )

        elif (
            self.source_type
            == self.SourceType.USER_REPORT
        ):
            if not self.user_report:
                errors["user_report"] = (
                    "Kullanıcı ihlali için "
                    "kullanıcı raporu gereklidir."
                )

        elif (
            self.source_type
            == self.SourceType.FALSE_REPORT
        ):
            report_sources = [
                bool(self.content_report),
                bool(self.user_report),
                bool(self.company_report),
            ]

            if sum(report_sources) != 1:
                errors["content_report"] = (
                    "Kötü niyetli raporlama ihlali tam olarak bir "
                    "rapor kaynağına bağlı olmalıdır."
                )

        self.description = (
            self.description or ""
        ).strip()

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"@{self.user.username} - "
            f"{self.get_source_type_display()}"
        )

class ReportRestriction(models.Model):

    class Kind(models.TextChoices):
        PROBATION = (
            "PROBATION",
            "Raporlama gözetimi",
        )
        FULL_BLOCK = (
            "FULL_BLOCK",
            "Şikayet ve raporlama kısıtı",
        )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="report_restrictions",
    )

    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        db_index=True,
    )

    starts_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
    )

    ends_at = models.DateTimeField(
        db_index=True,
    )

    trigger_violation = models.ForeignKey(
        "UserViolation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_report_restrictions",
    )

    reason = models.CharField(
        max_length=500,
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
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
                    "kind",
                    "ends_at",
                ),
                name="report_restriction_active",
            ),
        ]

    @property
    def is_active(self):
        now = timezone.now()
        return self.starts_at <= now < self.ends_at

    def __str__(self):
        return (
            f"@{self.user.username} - "
            f"{self.get_kind_display()}"
        )

