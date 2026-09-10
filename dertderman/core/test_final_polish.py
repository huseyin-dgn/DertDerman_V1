from datetime import timedelta
from io import BytesIO, StringIO
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.badges import BADGES as USER_BADGES, resolve_user_badges
from companies.badges import BADGES as COMPANY_BADGES, resolve_badges_for_companies, resolve_company_badges
from companies.category_seed import COMPANY_CATEGORY_NAMES, seed_company_categories
from companies.models import Company, CompanyCategory, CompanyMembership, CompanyResponse
from complaints.models import Complaint, ComplaintComment, ComplaintReaction


User = get_user_model()
PASSWORD = "StrongPass2026!"


def image_upload():
    output = BytesIO()
    Image.new("RGB", (80, 80), "#1d5fa7").save(output, "PNG")
    return SimpleUploadedFile("brand.png", output.getvalue(), content_type="image/png")


class UserBadgeV2Tests(TestCase):
    def test_all_ten_badges_are_derived_from_database_facts(self):
        user = User.objects.create_user(
            username="badge-v2-user", email="badge-v2@example.com", user_type="USER",
        )
        User.objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(days=500))
        company = Company.objects.create(name="User badge company")
        complaints = []
        for index in range(25):
            complaints.append(Complaint.objects.create(
                user=user, company=company, title=f"Public badge record {index}",
                description="Rozet hesaplaması için gerçek veritabanı kaydı açıklaması.",
                status=Complaint.Status.RESOLVED if index < 10 else Complaint.Status.PUBLISHED,
            ))
        helpers = [User.objects.create_user(
            username=f"helper-{index}", email=f"helper-{index}@example.com", user_type="USER",
        ) for index in range(25)]
        for index, complaint in enumerate(complaints):
            ComplaintComment.objects.create(complaint=complaint, author_user=helpers[index], body="Destek yorumu")
            ComplaintReaction.objects.create(complaint=complaint, user=helpers[index], reaction_type="👍")
        for index in range(10):
            ComplaintComment.objects.create(complaint=complaints[index], author_user=user, body="Topluluk katkısı")
        keys = {badge.key for badge in resolve_user_badges(User.objects.get(pk=user.pk))}
        self.assertEqual(keys, set(USER_BADGES))


class CompanyBadgeV2Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company_user = User.objects.create_user(
            username="badge-company-user", email="badge-company@example.com", user_type="COMPANY",
        )
        cls.consumer = User.objects.create_user(
            username="badge-consumer", email="badge-consumer@example.com", user_type="USER",
        )

    def make_performing_company(self):
        company = Company.objects.create(name="High performance", is_verified=True)
        responses = []
        now = timezone.now()
        for index in range(25):
            response_at = now - timedelta(days=100 - index * 5)
            complaint = Complaint.objects.create(
                user=self.consumer, company=company, title=f"Performance record {index}",
                description="Kurumsal rozet performans testi için yeterli açıklama.",
                status=Complaint.Status.RESOLVED if index < 18 else Complaint.Status.PUBLISHED,
            )
            Complaint.objects.filter(pk=complaint.pk).update(created_at=response_at - timedelta(hours=2))
            if index < 23:
                response = CompanyResponse.objects.create(
                    complaint=complaint, company=company, author_user=self.company_user,
                    body="Resmi şirket yanıtı.",
                )
                CompanyResponse.objects.filter(pk=response.pk).update(created_at=response_at)
                responses.append(response)
        return company

    def test_all_ten_company_badges_and_sample_size_rules(self):
        company = self.make_performing_company()
        self.assertEqual({badge.key for badge in resolve_company_badges(company)}, set(COMPANY_BADGES))

        small = Company.objects.create(name="Small sample", is_verified=True)
        complaint = Complaint.objects.create(
            user=self.consumer, company=small, title="Small sample complaint",
            description="Küçük örneklem davranışı için yeterli açıklama.", status=Complaint.Status.RESOLVED,
        )
        CompanyResponse.objects.create(
            complaint=complaint, company=small, author_user=self.company_user, body="İlk resmi yanıt.",
        )
        keys = {badge.key for badge in resolve_company_badges(small)}
        self.assertEqual(keys, {"company-new-member", "company-first-response"})

    def test_bulk_company_badges_have_constant_query_count(self):
        company = self.make_performing_company()
        others = [Company.objects.create(name=f"Other badge company {index}", is_verified=True) for index in range(5)]
        with CaptureQueriesContext(connection) as one:
            resolve_badges_for_companies((company.pk,))
        with CaptureQueriesContext(connection) as many:
            resolve_badges_for_companies((company.pk, *(item.pk for item in others)))
        self.assertEqual(len(one), len(many))
        self.assertLessEqual(len(many), 2)


@override_settings(MEDIA_ROOT=tempfile.gettempdir() + "/dertderman-final-polish-tests")
class CompanyLogoControlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Logo controls", is_verified=True)
        cls.other = Company.objects.create(name="Other logo company", is_verified=True)
        cls.owner = User.objects.create_user(username="logo-owner", email="logo-owner@example.com", password=PASSWORD, user_type="COMPANY")
        cls.support = User.objects.create_user(username="logo-support", email="logo-support@example.com", password=PASSWORD, user_type="COMPANY")
        CompanyMembership.objects.create(company=cls.company, user=cls.owner, role=CompanyMembership.Role.OWNER)
        CompanyMembership.objects.create(company=cls.company, user=cls.support, role=CompanyMembership.Role.SUPPORT)

    def test_logo_remove_is_post_csrf_role_and_current_company_scoped(self):
        self.company.logo = image_upload()
        self.company.save(update_fields=("logo",))
        url = reverse("companies:logo_remove")
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(url).status_code, 403)
        page = csrf_client.get(reverse("companies:profile"))
        token = page.cookies["csrftoken"].value
        self.assertRedirects(csrf_client.post(url, {"csrfmiddlewaretoken": token, "company_id": self.other.pk}), reverse("companies:profile"))
        self.company.refresh_from_db()
        self.assertFalse(self.company.logo)
        self.client.force_login(self.support)
        self.assertEqual(self.client.post(url).status_code, 403)


class CategoryAndPresentationTests(TestCase):
    def test_category_seed_is_idempotent(self):
        seed_company_categories(CompanyCategory)
        seed_company_categories(CompanyCategory)
        self.assertEqual(CompanyCategory.objects.filter(name__in=COMPANY_CATEGORY_NAMES).count(), 20)
        call_command("seed_company_categories", stdout=StringIO())
        self.assertEqual(CompanyCategory.objects.filter(name__in=COMPANY_CATEGORY_NAMES).count(), 20)

    def test_theme_switching_and_login_logout_flash_are_absent(self):
        for route in ("core:home", "accounts:login", "company_auth:login"):
            page = self.client.get(reverse(route))
            self.assertNotContains(page, "data-theme-toggle")
            self.assertNotContains(page, "dd-theme")
            self.assertNotContains(page, "prefers-color-scheme")
        user = User.objects.create_user(username="quiet-login", email="quiet@example.com", password=PASSWORD, user_type="USER", selected_avatar="avatar-1")
        response = self.client.post(reverse("accounts:login"), {"username": user.username, "password": PASSWORD}, follow=True)
        self.assertNotContains(response, "Başarıyla giriş yaptınız")
        response = self.client.post(reverse("accounts:logout"), follow=True)
        self.assertNotContains(response, "Oturumunuz güvenli şekilde kapatıldı")

    def test_discovery_and_corporate_content_ctas(self):
        home = self.client.get(reverse("core:home"))
        self.assertContains(home, "DertDerman Kimdir?")
        self.assertContains(home, "DertDerman'ı Tanıyın")
        self.assertContains(home, 'class="primary-action" href="/hakkimizda/"')
        about = self.client.get(reverse("core:about"))
        for heading in ("DERTDERMAN KİMDİR?", "NEDEN DERTDERMAN?", "NASIL ÇALIŞIR?", "KULLANICI İÇİN", "ŞİRKET İÇİN", "ŞEFFAFLIK VE TARAFSIZLIK", "PAYLAŞMADAN OLMAZ"):
            self.assertContains(about, heading, html=False)
