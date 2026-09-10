"""Responsive Public Complaint V2 QA against a disposable database."""
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
    from complaints.models import Complaint, ComplaintComment, ComplaintLike, ComplaintReaction
    from playwright.sync_api import sync_playwright, expect

    call_command("migrate", verbosity=0)
    password = secrets.token_urlsafe(24)
    owner = User.objects.create_user(username="qa-public-owner", email="qa-public-owner@example.com", password=password, user_type="USER")
    visitor = User.objects.create_user(username="qa-public-visitor", email="qa-public-visitor@example.com", password=password, user_type="USER")
    agent = User.objects.create_user(username="qa-public-agent", email="qa-public-agent@example.com", password=password, user_type="COMPANY")
    company = Company.objects.create(name="Mavi Teknoloji", is_verified=True)
    CompanyMembership.objects.create(user=agent, company=company, role="OWNER")
    complaints = []
    for index in range(12):
        complaints.append(Complaint.objects.create(
            user=owner, company=company,
            status="RESOLVED" if index % 4 == 0 else "PUBLISHED",
            title=f"Public deneyim kaydı {index + 1:02d}",
            description="Ürün ve destek süreciyle ilgili yaşadığım deneyimi çözüm beklentimle birlikte açıkça paylaşıyorum.",
        ))
    featured = complaints[-1]
    CompanyResponse.objects.create(company=company, complaint=featured, author_user=agent, body="Talebinizi inceledik ve çözüm seçeneklerini sizinle paylaştık.")
    ComplaintLike.objects.create(complaint=featured, user=visitor)
    ComplaintReaction.objects.create(complaint=featured, user=visitor, reaction_type="SUPPORT")
    for index in range(12):
        ComplaintComment.objects.create(complaint=featured, author_user=visitor, body=f"Topluluk yorumu {index + 1}: Bu deneyimin çözülmesini destekliyorum.")

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    server = make_server("127.0.0.1", 0, StaticFilesHandler(get_wsgi_application()), handler_class=QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    output = ROOT / "docs/public-complaint-v2-qa"
    output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "browser": "", "viewports": [], "js_errors": [], "checks": []}
    sizes = [(375, 812), (430, 932), (768, 1024), (1024, 768), (1366, 768), (1440, 900)]
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            report["browser"] = browser.version
            context = browser.new_context()
            page = context.new_page()
            page.on("pageerror", lambda error: report["js_errors"].append(str(error)))

            page.goto(origin + "/hesap/giris/")
            page.locator("[name=username]").fill(visitor.username)
            page.locator("[name=password]").fill(password)
            page.locator("button[type=submit]").click()
            page.wait_for_url(origin + "/panel/")

            for width, height in sizes:
                page.set_viewport_size({"width": width, "height": height})
                checks = []

                page.goto(origin + "/intro/?preview=1")
                page.wait_for_timeout(450)
                orbit = page.locator(".intro-orbit").bounding_box()
                wordmark = page.locator(".intro-wordmark").bounding_box()
                assert orbit and wordmark
                assert wordmark["x"] >= orbit["x"] and wordmark["y"] >= orbit["y"]
                assert wordmark["x"] + wordmark["width"] <= orbit["x"] + orbit["width"]
                assert wordmark["y"] + wordmark["height"] <= orbit["y"] + orbit["height"]
                assert page.locator(".intro-logo").count() == 0
                assert page.locator("img[src*='dert_derman.jpeg']").count() == 0
                checks.append("intro-wordmark")
                page.screenshot(path=str(output / f"intro-{width}.png"), full_page=True)

                page.goto(origin + "/")
                expect(page.locator(".home-complaint-preview .public-complaint-card")).to_have_count(4)
                expect(page.get_by_role("heading", name="En Güncel Şikayetler")).to_be_visible()
                checks.append("homepage-four")
                page.screenshot(path=str(output / f"home-{width}.png"), full_page=True)

                page.goto(origin + "/sikayetler/?q=Public")
                cards = page.locator(".public-two-column .public-complaint-card")
                expect(cards).to_have_count(8)
                first, second = cards.nth(0).bounding_box(), cards.nth(1).bounding_box()
                if width >= 1024:
                    assert first and second and abs(first["y"] - second["y"]) < 3 and second["x"] > first["x"]
                else:
                    assert first and second and second["y"] > first["y"]
                assert "q=Public" in page.locator(".dd-pagination a").last.get_attribute("href")
                checks.append("public-grid")
                page.screenshot(path=str(output / f"list-{width}.png"), full_page=True)

                page.goto(origin + f"/sikayetler/{featured.pk}/")
                expect(page.get_by_role("heading", name="Şirketin Cevabı")).to_be_visible()
                expect(page.get_by_role("heading", name="Topluluk Yorumları")).to_be_visible()
                expect(page.locator(".community-comment")).to_have_count(10)
                expect(page.locator(".interaction-bar")).to_be_visible()
                checks.append("interactions-comments")
                page.screenshot(path=str(output / f"detail-{width}.png"), full_page=True)

                page.goto(origin + "/sikayet-olustur/")
                expect(page.get_by_role("heading", name="Şikayetinizi Paylaşın")).to_be_visible()
                expect(page.get_by_role("heading", name="İyi bir şikayet nasıl yazılır?")).to_be_visible()
                expect(page.get_by_role("button", name="Şikayeti Gönder")).to_be_visible()
                checks.append("create-v2")
                page.screenshot(path=str(output / f"create-{width}.png"), full_page=True)

                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                nav_brand = page.locator(".compact-brand").first.bounding_box()
                assert nav_brand and nav_brand["height"] <= 48
                report["viewports"].append({"width": width, "checks": checks, "overflow": False})

            assert not report["js_errors"], report["js_errors"]
            report["checks"] = [
                "Original DERT DERMAN wordmark remains inside the ring without JPEG",
                "Public and USER compact SVG/CSS brand stays height-bounded",
                "Homepage renders exactly four newest complaints",
                "Public list is two columns on desktop and one on smaller screens",
                "Interaction bar, official response and ten-comment page render",
                "Complaint Create V2 fields, guide and CTA render without overflow",
            ]
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
    with tempfile.TemporaryDirectory(prefix="dd-public-v2-", ignore_cleanup_errors=True) as directory:
        run(directory)
