from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from blog.models import Post
from companies.models import Company, CompanyCategory
from complaints.models import Complaint
from core.management.commands.seed_demo_data import DEMO_MARKER, DEMO_PREFIX


class SmallPolishLayoutTests(TestCase):
    def test_homepage_has_exact_section_order_without_retired_sections(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        ordered_markers = (
            'class="stats-section"',
            'class="content-section complaint-feed-section"',
            'class="content-section process-section"',
            'class="content-section company-section"',
            'class="business-cta"',
            'class="content-section corporate-discovery"',
            'class="content-section editorial-section"',
        )
        positions = [html.index(marker) for marker in ordered_markers]
        self.assertEqual(positions, sorted(positions))
        for number in (1, 2, 3, 4, 7):
            self.assertContains(response, f'class="section-index">{number:02d}</p>', count=1)
        self.assertContains(response, 'class="business-mark"><span>05</span> DD / KURUM', count=1)
        self.assertContains(response, 'class="section-index corporate-discovery-index">06</p>', count=1)
        self.assertNotContains(response, 'class="content-section reasons-section"')
        self.assertNotContains(response, 'class="trust-section"')

    def test_about_page_retains_merged_value_and_transparency_content(self):
        response = self.client.get(reverse("core:about"))
        self.assertContains(response, "Doğru muhatap")
        self.assertContains(response, "İncelenen yayın")
        self.assertContains(response, "Tek yerde takip")
        self.assertContains(response, "ŞEFFAFLIK VE TARAFSIZLIK")

    def test_profile_edit_desktop_ratio_and_mobile_breakpoint_are_explicit(self):
        user = get_user_model().objects.create_user(
            username="profile-layout-user",
            email="profile-layout@example.invalid",
            password="safe-test-password",
            selected_avatar="avatar-1",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile_edit"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="profile-edit-form"')
        self.assertContains(response, "İletişim bilgileri")
        self.assertContains(response, "Profil avatarı")
        css = (Path(settings.BASE_DIR) / "static/css/identity-v1.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: minmax(360px, 2fr) minmax(500px, 3fr)", css)
        self.assertIn(".profile-edit-form { grid-template-columns: 1fr; }", css)

    @override_settings(DEBUG=True)
    def test_public_card_ctas_have_only_requested_visible_copy(self):
        call_command("seed_demo_data", stdout=StringIO())
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, ">İncele →</a>")
        self.assertContains(response, ">Yazıyı Oku →</a>")
        self.assertNotContains(response, "İncele<span class=\"visually-hidden\">")
        self.assertNotContains(response, "Yazıyı Oku<span class=\"visually-hidden\">")


@override_settings(DEBUG=True)
class DemoSeedCommandTests(TestCase):
    def demo_counts(self):
        return (
            Company.objects.filter(slug__startswith=DEMO_PREFIX).count(),
            Complaint.objects.filter(description__contains=DEMO_MARKER).count(),
            Post.objects.filter(slug__startswith=DEMO_PREFIX).count(),
            get_user_model().objects.filter(username__startswith=DEMO_PREFIX).count(),
        )

    def test_first_and_second_runs_are_idempotent_with_exact_product_counts(self):
        call_command("seed_demo_data", stdout=StringIO())
        first = self.demo_counts()
        self.assertEqual(first, (20, 20, 10, 10))
        self.assertEqual(
            Company.objects.filter(slug__startswith=DEMO_PREFIX, category__isnull=False).count(),
            20,
        )
        self.assertEqual(
            Company.objects.filter(slug__startswith=DEMO_PREFIX).values("category_id").distinct().count(),
            20,
        )
        call_command("seed_demo_data", stdout=StringIO())
        self.assertEqual(self.demo_counts(), first)

    def test_reset_rebuilds_demo_records_and_preserves_unmarked_records(self):
        User = get_user_model()
        owner = User.objects.create_user(
            username="real-local-user", email="real@example.invalid", password="safe-test-password"
        )
        category = CompanyCategory.objects.create(name="Korunacak Kategori")
        company = Company.objects.create(name="Korunacak Şirket", category=category)
        complaint = Complaint.objects.create(
            user=owner,
            company=company,
            title="Korunacak gerçek kayıt",
            description="Bu kayıt demo komutuna ait değildir ve reset sonrasında kalmalıdır.",
        )
        post = Post.objects.create(
            title="Korunacak yazı",
            excerpt="Demo komutundan bağımsız yazı.",
            content="Bu içerik reset sırasında kesinlikle korunmalıdır.",
            status=Post.Status.PUBLISHED,
        )
        call_command("seed_demo_data", stdout=StringIO())
        call_command("seed_demo_data", "--reset", stdout=StringIO())
        self.assertEqual(self.demo_counts(), (20, 20, 10, 10))
        self.assertTrue(User.objects.filter(pk=owner.pk).exists())
        self.assertTrue(Company.objects.filter(pk=company.pk).exists())
        self.assertTrue(Complaint.objects.filter(pk=complaint.pk).exists())
        self.assertTrue(Post.objects.filter(pk=post.pk).exists())
        self.assertTrue(CompanyCategory.objects.filter(pk=category.pk).exists())

    @override_settings(DEBUG=False)
    def test_production_mode_is_refused_without_explicit_override(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo_data", stdout=StringIO())
