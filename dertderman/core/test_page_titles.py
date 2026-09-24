import re
from html import unescape

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from companies.models import Company, CompanyMembership


class BrowserPageTitleTests(TestCase):
    def assert_page_title(self, url, expected):
        response = self.client.get(reverse(url))
        self.assertEqual(response.status_code, 200)
        match = re.search(r"<title>(.*?)</title>", response.content.decode(), re.DOTALL)
        self.assertIsNotNone(match)
        self.assertEqual(" ".join(unescape(match.group(1)).split()), expected)

    def test_public_and_auth_titles(self):
        for url, expected in (
            ("core:contact", "DertDerman | Bize Ulaşın"),
            ("blog:list", "DertDerman | Blog & Rehber"),
            ("complaints:public_list", "DertDerman | Şikayetler"),
            ("companies_public:company_list", "DertDerman | Şirketler"),
            ("accounts:login", "DertDerman | Giriş Yap"),
            ("accounts:register", "DertDerman | Hesap Oluştur"),
            ("accounts:password_reset", "DertDerman | Şifremi Unuttum"),
        ):
            with self.subTest(url=url):
                self.assert_page_title(url, expected)

    def test_private_panel_titles(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="title-user", email="title-user@example.com", password="TitleTest123!",
            user_type="USER", is_verified=True,
        )
        company_user = User.objects.create_user(
            username="title-company", email="title-company@example.com", password="TitleTest123!",
            user_type="COMPANY", is_verified=True,
        )
        admin = User.objects.create_user(
            username="title-admin", email="title-admin@example.com", password="TitleTest123!",
            user_type="ADMIN", is_staff=True, is_verified=True,
        )
        company = Company.objects.create(name="Title Test Company", is_verified=True)
        CompanyMembership.objects.create(
            user=company_user, company=company, role=CompanyMembership.Role.OWNER,
        )
        for account, cases in (
            (user, (
                ("dashboard:home", "DertDerman | Genel Bakış"),
                ("accounts:profile_edit", "DertDerman | Bilgilerimi Düzenle"),
                ("notifications:list", "DertDerman | Bildirimlerim"),
            )),
            (company_user, (
                ("companies:company_panel", "DertDerman | Genel Bakış"),
                ("companies:profile", "DertDerman | Şirket Profili"),
                ("companies:plan", "DertDerman | Paketim"),
            )),
            (admin, (
                ("adminx:home", "DertDerman | Yönetim - Genel Bakış"),
                ("adminx:company_list", "DertDerman | Yönetim - Şirketler"),
                ("adminx:contact_list", "DertDerman | Yönetim - İletişim Talepleri"),
            )),
        ):
            self.client.force_login(account)
            for url, expected in cases:
                with self.subTest(account=account.username, url=url):
                    self.assert_page_title(url, expected)
