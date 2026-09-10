"""Responsive Public Company Profile V2 QA against a disposable database."""
import json
import os
from pathlib import Path
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
    from companies.models import Company, CompanyCategory, CompanyResponse
    from complaints.models import Complaint, ComplaintComment, ComplaintLike, ComplaintReaction
    from playwright.sync_api import expect, sync_playwright

    call_command("migrate", verbosity=0)
    owner = User.objects.create_user(username="qa-profile-owner", email="owner@example.com", user_type="USER")
    visitor = User.objects.create_user(username="qa-profile-visitor", email="visitor@example.com", user_type="USER")
    agent = User.objects.create_user(username="qa-profile-agent", email="agent@example.com", user_type="COMPANY")
    category = CompanyCategory.objects.create(name="Teknoloji")
    company = Company.objects.create(
        name="Mavi Teknoloji",
        description="Dijital ürünler ve tüketici destek hizmetleri sunan doğrulanmış teknoloji şirketi.",
        website="https://example.com",
        email="destek@example.com",
        phone="+905551112233",
        category=category,
        is_verified=True,
    )
    complaints = []
    for index in range(8):
        complaint = Complaint.objects.create(
            user=owner,
            company=company,
            status="RESOLVED" if index % 3 == 0 else "PUBLISHED",
            title=f"Mavi Teknoloji deneyimi {index + 1:02d}",
            description="Ürün teslimatı ve destek süreciyle ilgili deneyimimi çözüm beklentimle birlikte ayrıntılı biçimde paylaşıyorum.",
        )
        complaints.append(complaint)
        if index < 5:
            CompanyResponse.objects.create(
                complaint=complaint,
                company=company,
                author_user=agent,
                body=f"Talebinizi inceledik. Çözüm adımlarını paylaşıyoruz; şirket yanıtı {index + 1}.",
            )
    ComplaintLike.objects.create(complaint=complaints[-1], user=visitor)
    ComplaintReaction.objects.create(complaint=complaints[-1], user=visitor, reaction_type="SUPPORT")
    ComplaintComment.objects.create(complaint=complaints[-1], author_user=visitor, body="Bu kaydı takip ediyorum.")

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    server = make_server("127.0.0.1", 0, StaticFilesHandler(get_wsgi_application()), handler_class=QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    output = ROOT / "docs/company-profile-v2-qa"
    output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "browser": "", "viewports": [], "js_errors": []}
    sizes = [(375, 812), (430, 932), (768, 1024), (1024, 768), (1366, 768), (1440, 900)]
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            report["browser"] = browser.version
            page = browser.new_page()
            page.on("pageerror", lambda error: report["js_errors"].append(str(error)))
            for width, height in sizes:
                page.set_viewport_size({"width": width, "height": height})
                page.goto(origin + f"/sirketler/{company.slug}/", wait_until="networkidle")
                expect(page.get_by_role("heading", name=company.name, exact=True)).to_be_visible()
                expect(page.locator(".company-profile-logo")).to_be_visible()
                expect(page.locator(".company-metric")).to_have_count(4)
                expect(page.locator(".company-complaint-card")).to_have_count(6)
                expect(page.locator(".company-filter-tabs a")).to_have_count(3)
                expect(page.locator(".company-profile-cta")).to_be_visible()
                expect(page.locator(".dd-pagination")).to_be_visible()
                expect(page.locator(".company-response-list article")).to_have_count(4)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                cards = page.locator(".company-complaint-card")
                first, second = cards.nth(0).bounding_box(), cards.nth(1).bounding_box()
                assert first and second
                if width <= 430:
                    assert second["y"] > first["y"] + first["height"] - 3
                else:
                    assert abs(first["y"] - second["y"]) < 3 and second["x"] > first["x"]
                metrics = page.locator(".company-metric")
                metric_first, metric_third = metrics.nth(0).bounding_box(), metrics.nth(2).bounding_box()
                assert metric_first and metric_third
                if width >= 1024:
                    assert abs(metric_first["y"] - metric_third["y"]) < 3
                else:
                    assert metric_third["y"] > metric_first["y"]
                logo = page.locator(".company-profile-logo").bounding_box()
                cta = page.locator(".company-profile-cta").bounding_box()
                assert logo and cta and logo["width"] <= 116 and cta["x"] + cta["width"] <= width
                page.screenshot(path=str(output / f"profile-{width}.png"), full_page=True)
                report["viewports"].append({"width": width, "overflow": False, "cards": 6, "metrics": 4})
            assert not report["js_errors"], report["js_errors"]
            report["passed"] = True
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        from django.db import connections

        connections.close_all()
        (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="dd-company-profile-v2-", ignore_cleanup_errors=True) as directory:
        run(directory)
