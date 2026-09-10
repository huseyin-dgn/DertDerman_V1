from io import BytesIO
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from companies.models import Company, CompanyMembership
from complaints.models import Complaint


User = get_user_model()
PASSWORD = "StrongPass2026!"


def logo_upload(name="company-logo.png"):
    output = BytesIO()
    Image.new("RGB", (120, 120), "#1768a2").save(output, "PNG")
    return SimpleUploadedFile(name, output.getvalue(), content_type="image/png")


class RoleAwarePublicUiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Role UI Company", selected_avatar="company-2")
        cls.complaint = Complaint.objects.create(
            user=User.objects.create_user(username="complaint-owner", email="owner-ui@example.com"),
            company=cls.company,
            title="Role aware public complaint",
            description="Role-aware public görünürlük testi için yeterli şikayet açıklaması.",
            status=Complaint.Status.PUBLISHED,
        )
        cls.consumer = User.objects.create_user(
            username="role-consumer", email="consumer-ui@example.com", password=PASSWORD, user_type="USER"
        )
        cls.company_user = User.objects.create_user(
            username="role-company", email="company-ui@example.com", password=PASSWORD, user_type="COMPANY"
        )
        cls.admin = User.objects.create_user(
            username="role-admin", email="admin-ui@example.com", password=PASSWORD,
            user_type="ADMIN", is_staff=True,
        )
        CompanyMembership.objects.create(
            user=cls.company_user, company=cls.company, role=CompanyMembership.Role.OWNER
        )

    def audited_responses(self):
        return (
            self.client.get(reverse("core:home")),
            self.client.get(reverse("companies_public:company_list")),
            self.client.get(reverse("core:about")),
            self.client.get(reverse("core:contact")),
            self.client.get(reverse("complaints:public_list")),
            self.client.get(reverse("companies_public:company_detail", args=[self.company.slug])),
            self.client.get(reverse("complaints:public_detail", args=[self.complaint.pk])),
        )

    def test_anonymous_sees_company_onboarding(self):
        home = self.client.get(reverse("core:home"))
        self.assertContains(home, reverse("company_auth:register"))
        self.assertContains(home, reverse("company_auth:login"))
        self.assertContains(home, "Şirket Ağına Katıl")
        self.assertContains(self.client.get(reverse("companies_public:company_list")), "Şirketler için DertDerman")

    def test_consumer_gets_consumer_only_public_ui(self):
        self.client.force_login(self.consumer)
        for response in self.audited_responses():
            self.assertNotContains(response, reverse("company_auth:register"))
            self.assertNotContains(response, reverse("company_auth:login"))
            self.assertNotContains(response, reverse("companies:company_panel"))
        home = self.client.get(reverse("core:home"))
        self.assertNotContains(home, "Şirket Ağına Katıl")
        self.assertNotContains(home, "Şirketler için")
        self.assertContains(home, reverse("complaints:create"))

    def test_company_gets_panel_ui_without_consumer_or_onboarding_actions(self):
        self.client.force_login(self.company_user)
        for response in self.audited_responses():
            self.assertNotContains(response, reverse("company_auth:register"))
            self.assertNotContains(response, reverse("company_auth:login"))
            self.assertNotContains(response, reverse("complaints:create"))
        home = self.client.get(reverse("core:home"))
        self.assertContains(home, reverse("companies:company_panel"))
        self.assertContains(self.client.get(reverse("core:about")), "Şirket Paneline Git")

    def test_admin_gets_admin_navigation_without_role_cta_mix(self):
        self.client.force_login(self.admin)
        for response in self.audited_responses():
            self.assertNotContains(response, reverse("company_auth:register"))
            self.assertNotContains(response, reverse("company_auth:login"))
            self.assertNotContains(response, reverse("companies:company_panel"))
            self.assertNotContains(response, reverse("complaints:create"))
        self.assertContains(self.client.get(reverse("core:home")), reverse("adminx:home"))


class UserAvatarControlUiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="avatar-control", email="avatar-control@example.com", password=PASSWORD,
            user_type="USER", selected_avatar="avatar-12",
        )
        self.client.force_login(self.user)

    def test_selected_avatar_and_twenty_trusted_assets_render_without_upload(self):
        response = self.client.get(reverse("accounts:profile_edit"))
        self.assertContains(response, "Profil avatarı")
        self.assertContains(response, "MEVCUT AVATAR")
        self.assertContains(response, "images/avatars/users/avatar-", count=21)
        self.assertContains(response, 'value="avatar-12"')
        self.assertContains(response, 'id="id_selected_avatar_11" checked')
        self.assertNotContains(response, 'type="file"')

    def test_avatar_change_works_and_invalid_key_is_blocked(self):
        valid = {"first_name": "Ada", "last_name": "Yılmaz", "email": self.user.email, "phone": "", "selected_avatar": "avatar-20"}
        self.assertRedirects(self.client.post(reverse("accounts:profile_edit"), valid), reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.selected_avatar, "avatar-20")
        invalid = {**valid, "selected_avatar": "../../company-1"}
        response = self.client.post(reverse("accounts:profile_edit"), invalid)
        self.assertEqual(response.status_code, 200)
        self.assertIn("selected_avatar", response.context["form"].errors)
        self.user.refresh_from_db()
        self.assertEqual(self.user.selected_avatar, "avatar-20")


@override_settings(MEDIA_ROOT=tempfile.gettempdir() + "/dertderman-role-media-tests")
class CompanyImageControlUiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Media Control", selected_avatar="company-4", is_verified=True)
        cls.other = Company.objects.create(name="Protected Other", selected_avatar="company-3", is_verified=True)
        cls.owner = User.objects.create_user(username="media-owner", email="media-owner@example.com", password=PASSWORD, user_type="COMPANY")
        cls.manager = User.objects.create_user(username="media-manager", email="media-manager@example.com", password=PASSWORD, user_type="COMPANY")
        cls.support = User.objects.create_user(username="media-support", email="media-support@example.com", password=PASSWORD, user_type="COMPANY")
        CompanyMembership.objects.create(user=cls.owner, company=cls.company, role=CompanyMembership.Role.OWNER)
        CompanyMembership.objects.create(user=cls.manager, company=cls.company, role=CompanyMembership.Role.MANAGER)
        CompanyMembership.objects.create(user=cls.support, company=cls.company, role=CompanyMembership.Role.SUPPORT)

    def test_manager_upload_ui_upload_remove_and_fallback_order(self):
        self.client.force_login(self.manager)
        page = self.client.get(reverse("companies:profile"))
        self.assertContains(page, "Şirket Görseli")
        self.assertContains(page, "data-logo-trigger")
        self.assertContains(page, 'class="cp-logo-native-input"')
        response = self.client.post(reverse("companies:profile"), {
            "name": self.company.name,
            "selected_avatar": "company-4",
            "logo": logo_upload(),
        })
        self.assertRedirects(response, reverse("companies:profile"))
        self.company.refresh_from_db()
        self.assertTrue(self.company.logo)
        page = self.client.get(reverse("companies:profile"))
        self.assertContains(page, "Görseli Değiştir")
        self.assertContains(page, "Görseli Kaldır")
        self.assertContains(page, "cp-button cp-button--danger")
        public = self.client.get(reverse("companies_public:company_detail", args=[self.company.slug]))
        self.assertContains(public, self.company.logo.url)

        self.assertRedirects(self.client.post(reverse("companies:logo_remove")), reverse("companies:profile"))
        self.company.refresh_from_db()
        self.assertFalse(self.company.logo)
        public = self.client.get(reverse("companies_public:company_detail", args=[self.company.slug]))
        self.assertContains(public, "images/avatars/companies/company-4.svg")
        Company.objects.filter(pk=self.company.pk).update(selected_avatar="")
        public = self.client.get(reverse("companies_public:company_detail", args=[self.company.slug]))
        self.assertContains(public, "company-profile-avatar-fallback")

    def test_support_is_read_only_and_cross_company_fields_do_not_change_target(self):
        self.client.force_login(self.support)
        page = self.client.get(reverse("companies:profile"))
        self.assertNotContains(page, "data-logo-trigger")
        self.assertEqual(self.client.post(reverse("companies:profile"), {"name": "Escalated"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("companies:logo_remove")).status_code, 403)

        self.client.force_login(self.owner)
        self.client.post(reverse("companies:profile"), {
            "name": "Media Control Updated", "selected_avatar": "company-5",
            "company_id": self.other.pk, "logo": logo_upload("new-logo.png"),
        })
        self.other.refresh_from_db()
        self.assertEqual(self.other.name, "Protected Other")
        self.assertFalse(self.other.logo)
