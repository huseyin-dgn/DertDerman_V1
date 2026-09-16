from datetime import timedelta

from django.contrib.auth import (
    get_user_model,
)
from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
)
from django.test import TestCase
from django.utils import timezone

from companies.models import (
    Company,
    CompanyMembership,
    CompanySubscription,
)

from .derman_company_services import (
    DermanCompanyResponseAlreadyExists,
    DermanCompanyResponseNotFound,
    DermanCompanyResponseProRequired,
    DermanCompanyResponseStateConflict,
    create_derman_company_response,
    update_derman_company_response,
)
from .models import (
    Complaint,
    DermanCompanyResponse,
    DermanPost,
)


User = get_user_model()


class DermanCompanyResponseServiceTests(
    TestCase
):
    @classmethod
    def setUpTestData(cls):
        cls.complaint_owner = (
            User.objects.create_user(
                username=(
                    "derman-company-"
                    "complaint-owner"
                ),
                email=(
                    "derman-company-"
                    "complaint-owner@example.com"
                ),
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.derman_author = (
            User.objects.create_user(
                username=(
                    "derman-company-"
                    "author"
                ),
                email=(
                    "derman-company-"
                    "author@example.com"
                ),
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.owner_user = (
            User.objects.create_user(
                username=(
                    "derman-company-owner"
                ),
                email=(
                    "derman-company-"
                    "owner@example.com"
                ),
                user_type=(
                    User.UserType.COMPANY
                ),
            )
        )

        cls.manager_user = (
            User.objects.create_user(
                username=(
                    "derman-company-manager"
                ),
                email=(
                    "derman-company-"
                    "manager@example.com"
                ),
                user_type=(
                    User.UserType.COMPANY
                ),
            )
        )

        cls.support_user = (
            User.objects.create_user(
                username=(
                    "derman-company-support"
                ),
                email=(
                    "derman-company-"
                    "support@example.com"
                ),
                user_type=(
                    User.UserType.COMPANY
                ),
            )
        )

        cls.other_company_user = (
            User.objects.create_user(
                username=(
                    "derman-other-company"
                ),
                email=(
                    "derman-other-company"
                    "@example.com"
                ),
                user_type=(
                    User.UserType.COMPANY
                ),
            )
        )

        cls.normal_user = (
            User.objects.create_user(
                username=(
                    "derman-normal-user"
                ),
                email=(
                    "derman-normal-user"
                    "@example.com"
                ),
                user_type=(
                    User.UserType.USER
                ),
            )
        )

        cls.company = (
            Company.objects.create(
                name=(
                    "Derman Company "
                    "Response Company"
                ),
                is_active=True,
                is_verified=True,
                approval_status=(
                    Company
                    .ApprovalStatus
                    .APPROVED
                ),
            )
        )

        cls.other_company = (
            Company.objects.create(
                name=(
                    "Derman Other "
                    "Company"
                ),
                is_active=True,
                is_verified=True,
                approval_status=(
                    Company
                    .ApprovalStatus
                    .APPROVED
                ),
            )
        )

        CompanyMembership.objects.create(
            user=cls.owner_user,
            company=cls.company,
            role=(
                CompanyMembership
                .Role
                .OWNER
            ),
            is_active=True,
        )

        CompanyMembership.objects.create(
            user=cls.manager_user,
            company=cls.company,
            role=(
                CompanyMembership
                .Role
                .MANAGER
            ),
            is_active=True,
        )

        CompanyMembership.objects.create(
            user=cls.support_user,
            company=cls.company,
            role=(
                CompanyMembership
                .Role
                .SUPPORT
            ),
            is_active=True,
        )

        CompanyMembership.objects.create(
            user=cls.other_company_user,
            company=cls.other_company,
            role=(
                CompanyMembership
                .Role
                .OWNER
            ),
            is_active=True,
        )

        cls.subscription = (
            CompanySubscription.objects.create(
                company=cls.company,
                plan=(
                    CompanySubscription
                    .Plan
                    .PRO
                ),
                billing_period=(
                    CompanySubscription
                    .BillingPeriod
                    .MONTHLY
                ),
                is_active=True,
                current_period_end=(
                    timezone.now()
                    + timedelta(days=30)
                ),
            )
        )

        cls.complaint = (
            Complaint.objects.create(
                user=cls.complaint_owner,
                company=cls.company,
                title=(
                    "Derman şirket cevabı "
                    "test şikayeti"
                ),
                description=(
                    "Derman şirket cevabı "
                    "servis testleri için "
                    "yeterince uzun açıklama."
                ),
                status=(
                    Complaint.Status.PUBLISHED
                ),
            )
        )

        cls.derman = (
            DermanPost.objects.create(
                complaint=cls.complaint,
                author_user=(
                    cls.derman_author
                ),
                body=(
                    "Bu yayınlanmış Derman "
                    "şirket cevabı testleri "
                    "için yeterince uzun."
                ),
                status=(
                    DermanPost.Status.PUBLISHED
                ),
                published_at=timezone.now(),
            )
        )

    def test_owner_can_create_response(
        self,
    ):
        response = (
            create_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.owner_user,
                body=(
                    "  Şirket olarak bu "
                    "çözümle ilgili resmi "
                    "yanıtımız budur.  "
                ),
            )
        )

        self.assertEqual(
            response.derman_id,
            self.derman.pk,
        )

        self.assertEqual(
            response.company_id,
            self.company.pk,
        )

        self.assertEqual(
            response.author_user_id,
            self.owner_user.pk,
        )

        self.assertEqual(
            response.body,
            (
                "Şirket olarak bu "
                "çözümle ilgili resmi "
                "yanıtımız budur."
            ),
        )

    def test_manager_can_create_response(
        self,
    ):
        response = (
            create_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.manager_user,
                body=(
                    "Yönetici tarafından "
                    "paylaşılan resmi şirket "
                    "yanıtı yeterince uzundur."
                ),
            )
        )

        self.assertEqual(
            response.author_user_id,
            self.manager_user.pk,
        )

    def test_support_cannot_create_response(
        self,
    ):
        with self.assertRaises(
            PermissionDenied
        ):
            create_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.support_user,
                body=(
                    "Destek rolü bu Derman "
                    "için resmi yanıt "
                    "paylaşamamalıdır."
                ),
            )

    def test_normal_user_cannot_create_response(
        self,
    ):
        with self.assertRaises(
            PermissionDenied
        ):
            create_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.normal_user,
                body=(
                    "Normal kullanıcı şirket "
                    "cevabı gönderememelidir."
                ),
            )

    def test_other_company_cannot_create_response(
        self,
    ):
        with self.assertRaises(
            PermissionDenied
        ):
            create_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.other_company_user,
                body=(
                    "Başka şirket bu Derman "
                    "için resmi yanıt "
                    "paylaşamamalıdır."
                ),
            )

    def test_standard_company_requires_pro(
        self,
    ):
        self.subscription.is_active = False

        self.subscription.save(
            update_fields=(
                "is_active",
                "updated_at",
            )
        )

        with self.assertRaises(
            DermanCompanyResponseProRequired
        ):
            create_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.owner_user,
                body=(
                    "Standart şirket hesabı "
                    "resmi Derman yanıtı "
                    "paylaşamamalıdır."
                ),
            )

    def test_expired_pro_requires_active_pro(
        self,
    ):
        self.subscription.current_period_end = (
            timezone.now()
            - timedelta(seconds=1)
        )

        self.subscription.save(
            update_fields=(
                "current_period_end",
                "updated_at",
            )
        )

        with self.assertRaises(
            DermanCompanyResponseProRequired
        ):
            create_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.owner_user,
                body=(
                    "Süresi dolmuş Pro hesabı "
                    "resmi Derman yanıtı "
                    "paylaşamamalıdır."
                ),
            )

    def test_resolved_complaint_blocks_create(
        self,
    ):
        self.complaint.status = (
            Complaint.Status.RESOLVED
        )

        self.complaint.save(
            update_fields=(
                "status",
                "updated_at",
            )
        )

        with self.assertRaises(
            DermanCompanyResponseStateConflict
        ):
            create_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.owner_user,
                body=(
                    "Çözülmüş şikayette yeni "
                    "şirket Derman cevabı "
                    "oluşturulmamalıdır."
                ),
            )

    def test_non_published_derman_blocks_create(
        self,
    ):
        self.derman.status = (
            DermanPost.Status.PENDING
        )

        self.derman.save(
            update_fields=(
                "status",
            )
        )

        with self.assertRaises(
            DermanCompanyResponseStateConflict
        ):
            create_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.owner_user,
                body=(
                    "Pending Derman için "
                    "şirket cevabı "
                    "oluşturulmamalıdır."
                ),
            )
    def test_duplicate_response_is_blocked(
        self,
    ):
        create_derman_company_response(
            derman_id=self.derman.pk,
            actor=self.owner_user,
            body=(
                "İlk resmi şirket cevabı "
                "oluşturuluyor ve geçerli."
            ),
        )

        with self.assertRaises(
            DermanCompanyResponseAlreadyExists
        ):
            create_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.manager_user,
                body=(
                    "Aynı Derman için ikinci "
                    "resmi cevap olmamalıdır."
                ),
            )

        self.assertEqual(
            DermanCompanyResponse.objects
            .filter(
                derman=self.derman,
                company=self.company,
            )
            .count(),
            1,
        )

    def test_short_body_is_rejected(
        self,
    ):
        with self.assertRaises(
            ValidationError
        ):
            create_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.owner_user,
                body="Çok kısa.",
            )

    def test_manager_can_update_response_and_original_author_is_preserved(
        self,
    ):
        response = (
            create_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.owner_user,
                body=(
                    "Şirketin ilk resmi "
                    "Derman yanıtı budur."
                ),
            )
        )

        updated = (
            update_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.manager_user,
                body=(
                    "  Şirketin güncellenmiş "
                    "resmi Derman yanıtı "
                    "artık budur.  "
                ),
            )
        )

        self.assertEqual(
            updated.pk,
            response.pk,
        )

        self.assertEqual(
            updated.body,
            (
                "Şirketin güncellenmiş "
                "resmi Derman yanıtı "
                "artık budur."
            ),
        )

        self.assertEqual(
            updated.author_user_id,
            self.owner_user.pk,
        )

    def test_update_missing_response_fails(
        self,
    ):
        with self.assertRaises(
            DermanCompanyResponseNotFound
        ):
            update_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.owner_user,
                body=(
                    "Olmayan şirket cevabı "
                    "güncellenememelidir."
                ),
            )

    def test_support_cannot_update_response(
        self,
    ):
        create_derman_company_response(
            derman_id=self.derman.pk,
            actor=self.owner_user,
            body=(
                "Güncelleme yetki kontrolü "
                "için ilk resmi cevap."
            ),
        )

        with self.assertRaises(
            PermissionDenied
        ):
            update_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.support_user,
                body=(
                    "Support kullanıcısı "
                    "cevabı değiştirememelidir."
                ),
            )

    def test_resolved_complaint_blocks_update(
        self,
    ):
        create_derman_company_response(
            derman_id=self.derman.pk,
            actor=self.owner_user,
            body=(
                "Şikayet çözülmeden önce "
                "oluşturulan resmi yanıt."
            ),
        )

        self.complaint.status = (
            Complaint.Status.RESOLVED
        )

        self.complaint.save(
            update_fields=(
                "status",
                "updated_at",
            )
        )

        with self.assertRaises(
            DermanCompanyResponseStateConflict
        ):
            update_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.owner_user,
                body=(
                    "Çözülmüş şikayette bu "
                    "cevap değiştirilememelidir."
                ),
            )

    def test_standard_company_cannot_update_response(
        self,
    ):
        create_derman_company_response(
            derman_id=self.derman.pk,
            actor=self.owner_user,
            body=(
                "Pro aktifken oluşturulan "
                "resmi şirket yanıtı."
            ),
        )

        self.subscription.is_active = False

        self.subscription.save(
            update_fields=(
                "is_active",
                "updated_at",
            )
        )

        with self.assertRaises(
            DermanCompanyResponseProRequired
        ):
            update_derman_company_response(
                derman_id=self.derman.pk,
                actor=self.owner_user,
                body=(
                    "Pro kapandıktan sonra "
                    "cevap değiştirilememelidir."
                ),
            )