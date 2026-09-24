from io import BytesIO
import tempfile

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Company, CompanyCategory, CompanyMembership
from .panel_services import update_company_profile


User = get_user_model()
PASSWORD = "StrongProfilePass2026!"


def image_upload(name="company.png", color=(20, 120, 180)):
    payload = BytesIO()
    Image.new("RGB", (24, 24), color).save(payload, format="PNG")
    return SimpleUploadedFile(name, payload.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=tempfile.gettempdir() + "/dertderman-company-profile-security")
class CompanyProfileSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = CompanyCategory.objects.create(name="Original Category")
        cls.other_category = CompanyCategory.objects.create(name="Other Category")
        cls.company = Company.objects.create(
            name="Approved Company",
            category=cls.category,
            email="company@example.com",
            description="Original description",
            website="https://old.example.com",
            phone="05000000000",
            approval_status=Company.ApprovalStatus.APPROVED,
            is_active=True,
            is_verified=True,
        )
        cls.other_company = Company.objects.create(
            name="Other Company",
            category=cls.other_category,
            email="other@example.com",
            approval_status=Company.ApprovalStatus.APPROVED,
            is_active=True,
            is_verified=True,
        )
        cls.owner = User.objects.create_user(
            username="profile-owner",
            email="owner@example.com",
            password=PASSWORD,
            user_type=User.UserType.COMPANY,
        )
        cls.manager = User.objects.create_user(
            username="profile-manager",
            email="manager@example.com",
            password=PASSWORD,
            user_type=User.UserType.COMPANY,
        )
        cls.support = User.objects.create_user(
            username="profile-support",
            email="support@example.com",
            password=PASSWORD,
            user_type=User.UserType.COMPANY,
        )
        cls.admin = User.objects.create_user(
            username="profile-admin",
            email="admin@example.com",
            password=PASSWORD,
            user_type=User.UserType.ADMIN,
        )
        for user, role in (
            (cls.owner, CompanyMembership.Role.OWNER),
            (cls.manager, CompanyMembership.Role.MANAGER),
            (cls.support, CompanyMembership.Role.SUPPORT),
        ):
            CompanyMembership.objects.create(
                user=user,
                company=cls.company,
                role=role,
                is_active=True,
            )

    def setUp(self):
        self.client.force_login(self.owner)
        self.url = reverse("companies:profile")

    def mutable_data(self, **extra):
        data = {
            "description": "Updated public description",
            "website": "https://new.example.com",
            "phone": "05551112233",
        }
        data.update(extra)
        return data

    def assert_identity_unchanged(self):
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Approved Company")
        self.assertEqual(self.company.category_id, self.category.pk)
        self.assertEqual(self.company.email, "company@example.com")

    def test_approved_company_cannot_change_name_category_or_email(self):
        attacks = (
            {"name": "Impersonated Brand"},
            {"category": str(self.other_category.pk)},
            {"email": "attacker@example.com"},
        )
        for attack in attacks:
            with self.subTest(attack=attack):
                response = self.client.post(self.url, self.mutable_data(**attack))
                self.assertEqual(response.status_code, 400)
                self.assert_identity_unchanged()

    def test_manual_post_cannot_change_locked_fields_or_target_company(self):
        response = self.client.post(
            self.url,
            self.mutable_data(
                name="Other Brand",
                category=str(self.other_category.pk),
                email="other-brand@example.com",
                company=str(self.other_company.pk),
                company_id=str(self.other_company.pk),
                approval_status=Company.ApprovalStatus.PENDING,
                is_active="false",
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assert_identity_unchanged()
        self.other_company.refresh_from_db()
        self.assertEqual(self.other_company.name, "Other Company")
        self.assertEqual(self.other_company.email, "other@example.com")

    def test_description_website_and_phone_remain_editable(self):
        response = self.client.post(self.url, self.mutable_data())
        self.assertRedirects(response, self.url)
        self.company.refresh_from_db()
        self.assertEqual(self.company.description, "Updated public description")
        self.assertEqual(self.company.website, "https://new.example.com")
        self.assertEqual(self.company.phone, "05551112233")
        self.assert_identity_unchanged()

    def test_first_logo_and_avatar_cannot_be_set_together(self):
        response = self.client.post(
            self.url,
            self.mutable_data(
                selected_avatar="company-5",
                logo=image_upload(),
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "Şirket logosu veya kurumsal simgeden yalnızca birini seçebilirsiniz.",
            status_code=400,
        )
        self.company.refresh_from_db()
        self.assertFalse(self.company.logo)
        self.assertEqual(self.company.selected_avatar, "")

    def test_first_logo_or_avatar_can_be_set_separately(self):
        logo_response = self.client.post(
            self.url,
            self.mutable_data(logo=image_upload("only-logo.png")),
        )
        self.assertRedirects(logo_response, self.url)
        self.company.refresh_from_db()
        self.assertTrue(self.company.logo)
        self.assertEqual(self.company.selected_avatar, "")

    def test_first_avatar_can_be_set_without_logo(self):
        response = self.client.post(
            self.url,
            self.mutable_data(selected_avatar="company-5"),
        )
        self.assertRedirects(response, self.url)
        self.company.refresh_from_db()
        self.assertFalse(self.company.logo)
        self.assertEqual(self.company.selected_avatar, "company-5")

    def test_existing_logo_cannot_be_replaced_or_removed(self):
        self.company.logo.save("existing.png", image_upload("existing.png"), save=True)
        original_name = self.company.logo.name

        replace = self.client.post(
            self.url,
            self.mutable_data(logo=image_upload("replacement.png")),
        )
        self.assertEqual(replace.status_code, 400)
        clear = self.client.post(reverse("companies:logo_remove"))
        self.assertEqual(clear.status_code, 403)
        legacy_clear = self.client.post(
            self.url,
            self.mutable_data(**{"logo-clear": "on"}),
        )
        self.assertEqual(legacy_clear.status_code, 400)
        self.company.refresh_from_db()
        self.assertEqual(self.company.logo.name, original_name)

    def test_existing_avatar_cannot_be_changed(self):
        Company.objects.filter(pk=self.company.pk).update(selected_avatar="company-2")
        response = self.client.post(
            self.url,
            self.mutable_data(selected_avatar="company-7"),
        )
        self.assertEqual(response.status_code, 400)
        self.company.refresh_from_db()
        self.assertEqual(self.company.selected_avatar, "company-2")

    def test_existing_avatar_blocks_later_logo(self):
        Company.objects.filter(
            pk=self.company.pk
        ).update(
            selected_avatar="company-2"
        )

        response = self.client.post(
            self.url,
            self.mutable_data(
                logo=image_upload(
                    "later-logo.png"
                ),
            ),
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        self.company.refresh_from_db()

        self.assertEqual(
            self.company.selected_avatar,
            "company-2",
        )

        self.assertFalse(
            self.company.logo
        )

    def test_existing_logo_blocks_later_avatar(self):
        self.company.logo.save(
            "existing-logo.png",
            image_upload(
                "existing-logo.png"
            ),
            save=True,
        )

        original_logo = (
            self.company.logo.name
        )

        response = self.client.post(
            self.url,
            self.mutable_data(
                selected_avatar="company-7",
            ),
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        self.company.refresh_from_db()

        self.assertEqual(
            self.company.logo.name,
            original_logo,
        )

        self.assertEqual(
            self.company.selected_avatar,
            "",
        )

    def test_support_cannot_edit_profile(self):
        self.client.force_login(self.support)
        response = self.client.post(self.url, self.mutable_data())
        self.assertEqual(response.status_code, 403)
        self.company.refresh_from_db()
        self.assertEqual(self.company.description, "Original description")

    def test_inactive_and_archived_company_cannot_edit_profile(self):
        for field, value in (("is_active", False), ("archived_at", timezone.now())):
            with self.subTest(field=field):
                original = getattr(self.company, field)
                Company.objects.filter(pk=self.company.pk).update(**{field: value})
                try:
                    response = self.client.post(self.url, self.mutable_data())
                    self.assertEqual(response.status_code, 403)
                finally:
                    Company.objects.filter(pk=self.company.pk).update(**{field: original})

    def test_service_rechecks_company_membership_and_target(self):
        with self.assertRaises(PermissionDenied):
            update_company_profile(
                user=self.owner,
                company_id=self.other_company.pk,
                data=self.mutable_data(),
                files={},
            )

    def test_admin_can_change_identity_fields(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("adminx:company_edit", args=[self.company.pk]),
            {
                "name": "Admin Renamed Company",
                "category": str(self.other_category.pk),
                "description": "Admin description",
                "selected_avatar": "company-8",
                "website": "https://admin.example.com",
                "email": "admin-updated@example.com",
                "phone": "05550001122",
                "logo": image_upload("admin-logo.png"),
            },
        )
        self.assertRedirects(
            response,
            reverse("adminx:company_edit", args=[self.company.pk]),
        )
        self.company.refresh_from_db()
        self.assertEqual(self.company.name, "Admin Renamed Company")
        self.assertEqual(self.company.category_id, self.other_category.pk)
        self.assertEqual(self.company.email, "admin-updated@example.com")
        self.assertEqual(self.company.selected_avatar, "company-8")
        self.assertTrue(self.company.logo)
