"""Light/dark responsive QA for product refinements using a disposable database."""
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
    from accounts.models import User
    from companies.models import Company, CompanyMembership, CompanyResponse
    from complaints.models import Complaint, ComplaintComment
    from core.models import ContactRequest
    from playwright.sync_api import expect, sync_playwright

    call_command("migrate", verbosity=0)
    password = secrets.token_urlsafe(18)
    owner = User.objects.create_user(username="qa-consumer", email="consumer@example.com", password=password, user_type="USER", selected_avatar="avatar-14")
    commenter = User.objects.create_user(username="qa-commenter", email="commenter@example.com", password=password, user_type="USER", selected_avatar="avatar-7")
    agent = User.objects.create_user(username="qa-company", email="company@example.com", password=password, user_type="COMPANY")
    admin = User.objects.create_user(username="qa-admin", email="admin@example.com", password=password, user_type="ADMIN", is_staff=True)
    company = Company.objects.create(name="Mavi Destek", description="Tüketici destek ve teknoloji hizmetleri.", website="https://example.com", is_verified=True, selected_avatar="company-4")
    CompanyMembership.objects.create(user=agent, company=company, role="OWNER")
    complaints = []
    for index in range(8):
        item = Complaint.objects.create(user=owner, company=company, title=f"Responsive deneyim {index + 1}", description="Responsive ürün deneyimi için yeterince uzun, açık ve çözüm odaklı örnek şikayet açıklaması.", status="RESOLVED" if index == 0 else "PUBLISHED")
        complaints.append(item)
    featured = complaints[-1]
    CompanyResponse.objects.create(complaint=featured, company=company, author_user=agent, body="Talebinizi inceledik ve çözüm adımlarını başlattık.")
    ComplaintComment.objects.create(complaint=featured, author_user=commenter, body="Benzer bir deneyim yaşadım; süreci takip ediyorum.")
    contact_request = ContactRequest.objects.create(name="QA Kullanıcısı", email="qa-contact@example.com", request_type="TECHNICAL", subject="Responsive iletişim talebi", message="Admin detay görünümü için güvenli örnek mesaj.")

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args): pass
    server = make_server("127.0.0.1", 0, StaticFilesHandler(get_wsgi_application()), handler_class=QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    output = ROOT / "docs/product-refinement-qa"
    output.mkdir(parents=True, exist_ok=True)
    sizes = [(375, 812), (430, 932), (768, 1024), (1024, 768), (1366, 768), (1440, 900)]
    report = {"passed": False, "browser": "", "checks": [], "js_errors": []}

    def set_theme(page, theme):
        page.evaluate("theme => { localStorage.setItem('dd-theme', theme); document.documentElement.dataset.theme = theme; }", theme)
        assert page.locator("html").get_attribute("data-theme") == theme

    def no_overflow(page):
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    def detail_ctas_are_blue_and_fit(page):
        visible_ctas = page.locator(".detail-cta:visible")
        for index in range(visible_ctas.count()):
            cta = visible_ctas.nth(index)
            result = cta.evaluate("""element => {
                const color = getComputedStyle(element).backgroundColor.match(/\\d+/g).map(Number);
                return {
                    isBlue: color[2] > color[0] && color[2] > color[1],
                    fits: element.scrollWidth <= element.clientWidth + 1,
                };
            }""")
            assert result["isBlue"], result
            assert result["fits"], result

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            report["browser"] = browser.version
            user_context = browser.new_context()
            user_page = user_context.new_page()
            user_page.on("pageerror", lambda error: report["js_errors"].append(str(error)))
            user_page.goto(origin + "/hesap/giris/")
            user_page.locator("[name=username]").fill(owner.username); user_page.locator("[name=password]").fill(password); user_page.locator("button[type=submit]").click()
            user_page.wait_for_url(origin + "/panel/")

            public_context = browser.new_context()
            public_page = public_context.new_page()
            public_page.on("pageerror", lambda error: report["js_errors"].append(str(error)))

            company_context = browser.new_context()
            company_page = company_context.new_page()
            company_page.on("pageerror", lambda error: report["js_errors"].append(str(error)))
            company_page.goto(origin + "/kurumsal/giris/")
            company_page.locator("[name=email]").fill(agent.email); company_page.locator("[name=password]").fill(password); company_page.locator("button[type=submit]").click()
            company_page.wait_for_url(origin + "/sirket-panel/")

            admin_context = browser.new_context()
            admin_page = admin_context.new_page()
            admin_page.on("pageerror", lambda error: report["js_errors"].append(str(error)))
            admin_page.goto(origin + "/yonetim/giris/")
            admin_page.locator("[name=username]").fill(admin.username); admin_page.locator("[name=password]").fill(password); admin_page.locator("button[type=submit]").click()
            admin_page.wait_for_url(origin + "/yonetim/")

            user_page.goto(origin + "/hesap/profil/duzenle/")
            expect(user_page.locator(".avatar-presets img[src*='/avatars/users/']")).to_have_count(20)
            expect(user_page.locator(".avatar-preset-option:has(input:checked) .avatar-choice-check")).to_be_visible()
            assert user_page.locator(".avatar-presets img").evaluate_all(
                "images => images.every(image => image.complete && image.naturalWidth > 0)"
            )

            user_page.goto(origin + f"/sikayetler/{featured.pk}/")
            expect(user_page.get_by_text("Tepkiyi Kaydet", exact=True)).to_have_count(0)
            reaction_buttons = user_page.locator(".emoji-option")
            reaction_buttons.nth(0).click()
            user_page.wait_for_load_state("networkidle")
            expect(user_page.locator(".emoji-option.is-active")).to_have_count(1)
            reaction_buttons = user_page.locator(".emoji-option")
            reaction_buttons.nth(1).click()
            user_page.wait_for_load_state("networkidle")
            expect(user_page.locator(".emoji-option.is-active")).to_have_count(1)
            user_page.locator(".emoji-option.is-active").click()
            user_page.wait_for_load_state("networkidle")
            expect(user_page.locator(".emoji-option.is-active")).to_have_count(0)

            public_page.goto(origin + "/bize-ulasin/")
            public_page.locator("[name=name]").fill("QA İletişim")
            public_page.locator("[name=email]").fill("gecersiz")
            public_page.locator("[name=request_type]").select_option("GENERAL")
            public_page.locator("[name=subject]").fill("QA form durumu")
            public_page.locator("[name=message]").fill("Responsive form doğrulaması için yeterli mesaj.")
            public_page.locator(".contact-form-card form").evaluate("form => form.submit()")
            public_page.wait_for_load_state("networkidle")
            expect(public_page.locator("[name=email][aria-invalid=true]")).to_be_visible()
            public_page.locator("[name=email]").fill("qa-browser@example.com")
            public_page.locator("button[type=submit]").click()
            public_page.wait_for_url(origin + "/bize-ulasin/?sent=1")
            expect(public_page.locator(".contact-success")).to_be_visible()

            public_routes = ("/", "/sikayetler/", "/sirketler/", f"/sirketler/{company.slug}/", f"/sikayetler/{featured.pk}/", "/hakkimizda/", "/bize-ulasin/")
            user_routes = ("/panel/", "/sikayetlerim/", f"/sikayetlerim/{featured.pk}/", f"/sikayetlerim/{featured.pk}/duzenle/", "/hesap/profil/", "/hesap/profil/duzenle/")
            for width, height in sizes:
                for theme in ("light", "dark"):
                    public_page.set_viewport_size({"width": width, "height": height})
                    public_page.goto(origin + "/hesap/kayit/", wait_until="networkidle"); set_theme(public_page, theme)
                    expect(public_page.locator(".avatar-presets--register img[src*='/avatars/users/']")).to_have_count(20)
                    expect(public_page.locator("input[type=file]")).to_have_count(0); no_overflow(public_page)
                    assert public_page.locator(".avatar-presets--register img").evaluate_all("images => images.every(image => image.complete && image.naturalWidth > 0)")
                    for route in ("/hakkimizda/", "/bize-ulasin/"):
                        public_page.goto(origin + route, wait_until="networkidle"); set_theme(public_page, theme); no_overflow(public_page)
                        expect(public_page.locator("footer a[href='/hakkimizda/']")).to_have_count(1)
                        expect(public_page.locator("footer a[href='/bize-ulasin/']")).to_have_count(1)
                    user_page.set_viewport_size({"width": width, "height": height})
                    for route in public_routes + user_routes:
                        user_page.goto(origin + route, wait_until="networkidle")
                        set_theme(user_page, theme); no_overflow(user_page); detail_ctas_are_blue_and_fit(user_page)
                        expect(user_page.locator("[data-theme-toggle]").first).to_be_visible()
                    user_page.goto(origin + "/hesap/profil/duzenle/"); set_theme(user_page, theme)
                    expect(user_page.locator(".avatar-presets input")).to_have_count(20)
                    expect(user_page.locator(".avatar-presets img[src*='/avatars/users/']")).to_have_count(20)
                    expect(user_page.locator(".avatar-preset-option:has(input:checked) .avatar-choice-check")).to_be_visible()
                    expect(user_page.locator("input[type=file]")).to_have_count(0); no_overflow(user_page)
                    if width in (375, 1440):
                        user_page.screenshot(path=str(output / f"avatar-selector-{theme}-{width}.png"), full_page=True)
                    user_page.goto(origin + f"/sikayetler/{featured.pk}/"); set_theme(user_page, theme)
                    expect(user_page.locator(".public-user-badge").first).to_be_visible()
                    expect(user_page.get_by_text("Tepkiyi Kaydet", exact=True)).to_have_count(0)
                    expect(user_page.locator(".emoji-picker")).to_be_visible(); expect(user_page.locator(".community-comment")).to_be_visible(); expect(user_page.locator(".official-response")).to_be_visible(); no_overflow(user_page)
                    if width in (375, 1440):
                        user_page.screenshot(path=str(output / f"public-detail-{theme}-{width}.png"), full_page=True)
                    user_page.goto(origin + f"/sikayetlerim/{featured.pk}/"); set_theme(user_page, theme)
                    user_page.locator("[data-withdraw-open]").click(); expect(user_page.locator("[data-withdraw-dialog]")).to_be_visible(); user_page.locator("[data-withdraw-close]").click(); no_overflow(user_page)

                    company_page.set_viewport_size({"width": width, "height": height})
                    company_page.goto(origin + "/sirket-panel/profil/", wait_until="networkidle"); set_theme(company_page, theme)
                    expect(company_page.locator("input[type=file]")).to_be_visible(); expect(company_page.locator(".company-avatar-presets input")).to_have_count(9); expect(company_page.locator(".cp-logo-preview img[src*='/avatars/companies/']")).to_be_visible(); expect(company_page.locator("[data-theme-toggle]")).to_be_visible(); no_overflow(company_page)
                    admin_page.set_viewport_size({"width": width, "height": height})
                    for route in ("/yonetim/iletisim-talepleri/", f"/yonetim/iletisim-talepleri/{contact_request.pk}/"):
                        admin_page.goto(origin + route, wait_until="networkidle"); set_theme(admin_page, theme); no_overflow(admin_page)
                    if width in (375, 1440):
                        user_page.screenshot(path=str(output / f"complaint-{theme}-{width}.png"), full_page=True)
                        company_page.screenshot(path=str(output / f"company-profile-{theme}-{width}.png"), full_page=True)
                    report["checks"].append({"width": width, "theme": theme, "overflow": False, "surfaces": 18})
            assert not report["js_errors"], report["js_errors"]
            report["passed"] = True
            browser.close()
    finally:
        server.shutdown(); server.server_close()
        from django.db import connections
        connections.close_all()
        (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="dd-product-qa-", ignore_cleanup_errors=True) as directory:
        run(directory)
