"""Responsive visual/interaction QA for the light-only final polish."""
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from wsgiref.simple_server import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def run(directory):
    from django.conf import settings
    settings.DATABASES["default"]["NAME"] = Path(directory) / "qa.sqlite3"
    settings.MEDIA_ROOT = Path(directory) / "media"
    import django
    django.setup()
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application
    from django.utils import timezone
    from accounts.models import User
    from companies.models import Company, CompanyMembership, CompanyResponse
    from complaints.models import Complaint, ComplaintComment, ComplaintReaction
    from playwright.sync_api import expect, sync_playwright

    call_command("migrate", verbosity=0)
    password = secrets.token_urlsafe(18)
    consumer = User.objects.create_user(username="qa-polish-user", email="user@example.com", password=password, user_type="USER", selected_avatar="avatar-14", first_name="Ada", last_name="Yılmaz")
    User.objects.filter(pk=consumer.pk).update(date_joined=timezone.now() - timezone.timedelta(days=500))
    company_user = User.objects.create_user(username="qa-polish-company", email="company@example.com", password=password, user_type="COMPANY")
    company = Company.objects.create(name="Mavi Destek", description="Tüketici destek ve teknoloji hizmetleri.", website="https://example.com", is_verified=True, selected_avatar="company-4")
    CompanyMembership.objects.create(user=company_user, company=company, role="OWNER")
    complaints = []
    for index in range(25):
        response_at = timezone.now() - timezone.timedelta(days=120 - index * 5)
        item = Complaint.objects.create(user=consumer, company=company, title=f"Responsive deneyim {index + 1}", description="Responsive ürün deneyimi için yeterince uzun, açık ve çözüm odaklı örnek şikayet açıklaması.", status="RESOLVED" if index < 18 else "PUBLISHED")
        Complaint.objects.filter(pk=item.pk).update(created_at=response_at - timezone.timedelta(hours=2))
        complaints.append(item)
        helper = User.objects.create_user(username=f"qa-helper-{index}", email=f"helper-{index}@example.com", user_type="USER")
        ComplaintComment.objects.create(complaint=item, author_user=helper, body="Bu deneyime destek veriyorum.")
        ComplaintReaction.objects.create(complaint=item, user=helper, reaction_type="👍")
        response = CompanyResponse.objects.create(complaint=item, company=company, author_user=company_user, body="Talebinizi inceledik ve çözüm adımlarını başlattık.")
        CompanyResponse.objects.filter(pk=response.pk).update(created_at=response_at)
    for item in complaints[:10]:
        ComplaintComment.objects.create(complaint=item, author_user=consumer, body="Topluluğa faydalı takip notu.")

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    server = make_server("127.0.0.1", 0, StaticFilesHandler(get_wsgi_application()), handler_class=QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    output = ROOT / "docs/final-polish-qa"
    output.mkdir(parents=True, exist_ok=True)
    sizes = ((375, 812), (430, 932), (768, 1024), (1024, 768), (1366, 768), (1440, 900))
    report = {"passed": False, "browser": "", "checks": [], "js_errors": []}

    def no_overflow(page):
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), page.url

    def blue_ctas_fit(page):
        ctas = page.locator(".detail-cta:visible, .corporate-discovery-card .primary-action:visible")
        for index in range(ctas.count()):
            result = ctas.nth(index).evaluate(r"""element => { const c=getComputedStyle(element); const rgb=c.backgroundColor.match(/\d+/g).map(Number); return {blue:rgb[2]>rgb[0]&&rgb[2]>rgb[1],fit:element.scrollWidth<=element.clientWidth+1}; }""")
            assert result["blue"] and result["fit"], result

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            report["browser"] = browser.version
            public_page = browser.new_page()
            user_page = browser.new_page()
            company_page = browser.new_page()
            for page in (public_page, user_page, company_page):
                page.on("pageerror", lambda error: report["js_errors"].append(str(error)))

            user_page.goto(origin + "/hesap/giris/")
            user_page.locator("[name=username]").fill(consumer.username)
            user_page.locator("[name=password]").fill(password)
            user_page.locator("button[type=submit]").click()
            user_page.wait_for_url(origin + "/panel/")
            company_page.goto(origin + "/kurumsal/giris/")
            company_page.locator("[name=email]").fill(company_user.email)
            company_page.locator("[name=password]").fill(password)
            company_page.locator("button[type=submit]").click()
            company_page.wait_for_url(origin + "/sirket-panel/")

            logo_path = Path(directory) / "qa-logo.png"
            from PIL import Image
            Image.new("RGB", (96, 96), "#1d5fa7").save(logo_path)

            for width, height in sizes:
                for page in (public_page, user_page, company_page):
                    page.set_viewport_size({"width": width, "height": height})

                public_page.goto(origin + "/hesap/kayit/", wait_until="networkidle")
                expect(public_page.locator(".avatar-presets--register img")).to_have_count(20)
                expect(public_page.locator("input[name=selected_avatar]")).to_have_count(20)
                expect(public_page.locator("input[type=file]")).to_have_count(0)
                no_overflow(public_page)

                for route in ("/", "/hakkimizda/", "/bize-ulasin/", "/sirketler/", f"/sirketler/{company.slug}/"):
                    public_page.goto(origin + route, wait_until="networkidle")
                    expect(public_page.locator("[data-theme-toggle]")).to_have_count(0)
                    no_overflow(public_page)
                    blue_ctas_fit(public_page)
                public_page.goto(origin + "/")
                expect(public_page.locator(".corporate-discovery-card")).to_have_count(2)
                public_page.goto(origin + f"/sirketler/{company.slug}/")
                expect(public_page.locator(".public-company-badges .achievement-badge")).to_have_count(10)

                user_page.goto(origin + "/hesap/profil/", wait_until="networkidle")
                expect(user_page.locator(".profile-avatar")).to_be_visible()
                expect(user_page.locator(".achievement-badge")).to_have_count(10)
                expect(user_page.locator(".profile-primary-badge")).to_be_visible()
                no_overflow(user_page)
                user_page.goto(origin + "/hesap/profil/duzenle/", wait_until="networkidle")
                expect(user_page.locator(".avatar-presets img")).to_have_count(20)
                expect(user_page.locator(".avatar-preset-option:has(input:checked) .avatar-choice-check")).to_be_visible()
                expect(user_page.locator("input[type=file]")).to_have_count(0)
                no_overflow(user_page)

                company_page.goto(origin + "/sirket-panel/profil/", wait_until="networkidle")
                expect(company_page.locator(".cp-logo-pick")).to_be_visible()
                expect(company_page.locator(".cp-logo-native-input")).to_be_hidden()
                expect(company_page.locator(".company-avatar-presets input")).to_have_count(9)
                expect(company_page.locator(".company-badge-showcase .achievement-badge")).to_have_count(10)
                company_page.locator(".cp-logo-native-input").set_input_files(str(logo_path))
                expect(company_page.locator("[data-logo-name]")).to_have_text("qa-logo.png")
                expect(company_page.locator(".cp-logo-upload-image")).to_be_visible()
                no_overflow(company_page)

                if width in (375, 1440):
                    company_page.screenshot(path=str(output / f"company-profile-{width}.png"), full_page=True)
                    user_page.goto(origin + "/hesap/profil/")
                    user_page.screenshot(path=str(output / f"user-profile-{width}.png"), full_page=True)
                    user_page.goto(origin + "/hesap/profil/duzenle/")
                    user_page.screenshot(path=str(output / f"user-profile-edit-{width}.png"), full_page=True)
                    for route, name in (("/", "homepage"), ("/hakkimizda/", "about"), ("/bize-ulasin/", "contact"), (f"/sirketler/{company.slug}/", "company-public")):
                        if route == "/":
                            public_page.evaluate("sessionStorage.setItem('dd_intro_returning', '1')")
                        public_page.goto(origin + route)
                        public_page.screenshot(path=str(output / f"{name}-{width}.png"), full_page=True)

                report["checks"].append({"width": width, "overflow": False, "surfaces": 10})
            assert not report["js_errors"], report["js_errors"]
            report["passed"] = True
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="dd-final-polish-qa-", ignore_cleanup_errors=True) as directory:
        run(directory)
