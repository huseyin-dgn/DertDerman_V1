"""Optional browser QA: python scripts/qa_admin_v2.py (requires Playwright + Edge).

Uses a disposable database; no accounts or sample content enter the project DB.
"""
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
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from django.utils import timezone
    from accounts.models import User
    from companies.models import Company, CompanyCategory, CompanyMembership
    from complaints.models import Complaint
    from blog.models import Post
    from playwright.sync_api import sync_playwright

    call_command("migrate", verbosity=0)
    password = secrets.token_urlsafe(24)
    admin = User.objects.create_user(username="qa-admin", email="qa-admin@example.com", password=password,
                                     first_name="Deniz", last_name="Yılmaz", user_type="ADMIN")
    reader = User.objects.create_user(username="qa-reader", email="qa-reader@example.com")
    agent = User.objects.create_user(username="qa-company", email="qa-company@example.com", user_type="COMPANY")
    category = CompanyCategory.objects.create(name="Teknoloji ve İletişim")
    titles = ["İade süreci hakkında geri dönüş bekliyorum", "Teslimat tarihi için bilgilendirme talebi",
              "Abonelik iptalinden sonra kesilen ücret", "Siparişim eksik teslim edildi", "Teknik destek talebimin takibi"]
    for i in range(17):
        company = Company.objects.create(name=f"Kurumsal İletişim {i + 1}", category=category,
            email=f"iletisim{i}@example.com", approval_status="PENDING" if i % 2 else "APPROVED", is_verified=i % 2 == 0)
        CompanyMembership.objects.create(user=agent, company=company, role="OWNER", is_active=i % 2 == 0)
        Complaint.objects.create(user=reader, company=company, title=titles[i % len(titles)],
            description="Başvurumu ilettim. Sürecin güncel durumu hakkında bilgi almak istiyorum.",
            status="PENDING" if i < 10 else "PUBLISHED" if i < 15 else "RESOLVED")
        Post.objects.create(title=f"Tüketici deneyimi rehberi {i + 1}", excerpt="Başvuru ve takip süreçleri",
            content="Başvurunuzu adım adım takip edin.", author=admin if i else None,
            status="PUBLISHED" if i % 2 else "DRAFT", published_at=timezone.now() if i % 2 else None)

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    server = make_server("127.0.0.1", 0, StaticFilesHandler(get_wsgi_application()), handler_class=QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    output = ROOT / "docs" / "admin-v2-qa"
    output.mkdir(parents=True, exist_ok=True)
    report = {"viewports": [], "checks": [], "js_errors": []}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
            page.on("pageerror", lambda error: report["js_errors"].append(str(error)))
            page.goto(origin + "/yonetim/giris/")
            page.get_by_label("Kullanıcı adı", exact=True).fill("qa-admin")
            page.get_by_label("Şifre", exact=True).fill(password)
            page.get_by_role("button", name="Giriş Yap", exact=True).click()
            page.wait_for_url(origin + "/yonetim/")
            routes = ["/yonetim/", "/yonetim/sikayetler/", "/yonetim/sirket-basvurulari/",
                      "/yonetim/sirketler/", "/yonetim/kullanicilar/", "/yonetim/blog/",
                      "/yonetim/bildirimler/", "/yonetim/aktivite/", "/yonetim/ana-sayfa/",
                      "/yonetim/sikayetler/1/", "/yonetim/sirket-basvurulari/2/",
                      "/yonetim/sirketler/1/duzenle/", "/yonetim/kullanicilar/2/", "/yonetim/blog/1/duzenle/"]
            for width, height in [(1440, 900), (1366, 768), (1024, 768), (768, 1024), (430, 932), (375, 812)]:
                page.set_viewport_size({"width": width, "height": height})
                for route in routes:
                    response = page.goto(origin + route)
                    assert response.status == 200, (route, response.status)
                    dimensions = page.evaluate("({width: innerWidth, scroll: document.documentElement.scrollWidth})")
                    assert dimensions["scroll"] <= width, (route, width, dimensions)
                    assert page.locator('.ad-nav [aria-current="page"]').count() == 1, route
                    if route in routes[:3]:
                        key = "dashboard" if route == "/yonetim/" else route.strip('/').split('/')[-1]
                        page.screenshot(path=str(output / f"{key}-{width}.png"), full_page=True)
                report["viewports"].append({"width": width, "height": height, "pages": len(routes), "overflow": False})
            page.goto(origin + "/yonetim/")
            toggle = page.get_by_role("button", name="Yönetim menüsü", exact=True)
            toggle.click()
            assert toggle.get_attribute("aria-expanded") == "true"
            assert page.locator('.ad-sidebar').evaluate("el => !el.inert")
            page.screenshot(path=str(output / "drawer-375.png"))
            page.keyboard.press("Escape")
            assert toggle.get_attribute("aria-expanded") == "false"
            assert toggle.evaluate("el => el === document.activeElement")
            report["checks"].append("Mobile drawer, Escape, focus restoration")

            page.set_viewport_size({"width": 1440, "height": 900})
            page.goto(origin + "/yonetim/sikayetler/")
            page.get_by_label("Ara", exact=True).fill("talep")
            page.get_by_role("button", name="Uygula", exact=True).click()
            assert "q=talep" in page.url
            page.goto(origin + "/yonetim/sikayetler/?status=PENDING")
            page.get_by_role("link", name="Sayfa 2", exact=True).click()
            assert "status=PENDING" in page.url and "page=2" in page.url
            assert page.locator('tbody tr').count() == 5
            report["checks"].append("Search, filter preservation, page 2 with five records")

            page.goto(origin + "/yonetim/sikayetler/1/")
            page.get_by_role("button", name="Reddet", exact=True).click()
            assert page.locator('dialog[open]').count() == 1
            page.screenshot(path=str(output / "confirmation-1440.png"))
            page.get_by_role("button", name="Vazgeç", exact=True).click()
            assert page.get_by_role("button", name="Reddet", exact=True).is_visible()
            page.get_by_role("button", name="Reddet", exact=True).click()
            page.get_by_role("button", name="Reddet ve tamamla", exact=True).click()
            page.wait_for_load_state("networkidle")
            assert page.locator('.feedback-success').is_visible()
            report["checks"].append("Reject confirmation cancel/confirm, POST/CSRF and success feedback")
            page.goto(origin + "/yonetim/sirket-basvurulari/2/")
            page.get_by_role("button", name="Reddet", exact=True).click()
            page.get_by_role("button", name="Reddet ve tamamla", exact=True).click()
            page.wait_for_load_state("networkidle")
            assert page.locator('.feedback-success').is_visible()
            report["checks"].append("Company rejection preserves submitter action value")
            page.goto(origin + "/yonetim/sirketler/?q=olmayan-kayit")
            assert page.locator('.ad-empty').is_visible()
            page.screenshot(path=str(output / "empty-state-1440.png"))
            report["checks"].append("Filtered empty state")
            assert not report["js_errors"], report["js_errors"]
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        from django.db import connections
        connections.close_all()
        (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="dertderman-admin-qa-") as directory:
        run(directory)
