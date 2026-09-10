"""Real-browser responsive QA for the homepage/profile small-polish pass."""
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
    from core.management.commands.seed_demo_data import DEMO_PREFIX
    from playwright.sync_api import expect, sync_playwright

    call_command("migrate", verbosity=0)
    call_command("seed_demo_data", verbosity=0)
    password = "qa-small-polish-password"
    consumer = User.objects.get(username=f"{DEMO_PREFIX}user-01")
    consumer.set_password(password)
    consumer.save(update_fields=["password"])

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    server = make_server(
        "127.0.0.1", 0, StaticFilesHandler(get_wsgi_application()), handler_class=QuietHandler
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    sizes = ((375, 812), (430, 932), (768, 1024), (1024, 768), (1366, 768), (1440, 900))
    output = ROOT / "docs/small-polish-qa"
    output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "browser": "", "viewports": [], "js_errors": []}

    def no_overflow(page):
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), page.url

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            report["browser"] = browser.version
            public_page = browser.new_page()
            user_page = browser.new_page()
            for page in (public_page, user_page):
                page.on("pageerror", lambda error: report["js_errors"].append(str(error)))

            user_page.goto(origin + "/hesap/giris/")
            user_page.locator("[name=username]").fill(consumer.username)
            user_page.locator("[name=password]").fill(password)
            user_page.locator("button[type=submit]").click()
            user_page.wait_for_url(origin + "/panel/")

            public_page.goto(origin + "/hakkimizda/")
            public_page.evaluate("sessionStorage.setItem('dd_intro_returning', '1')")

            for width, height in sizes:
                for page in (public_page, user_page):
                    page.set_viewport_size({"width": width, "height": height})

                public_page.goto(origin + "/", wait_until="networkidle")
                sections = public_page.locator(
                    ".stats-section, .complaint-feed-section, .process-section, "
                    ".company-section, .business-cta, .corporate-discovery, .editorial-section"
                )
                expect(sections).to_have_count(7)
                expect(public_page.locator(".reasons-section, .trust-section")).to_have_count(0)
                assert public_page.locator(".section-index").all_inner_texts() == ["01", "02", "03", "04", "06", "07"]
                expect(public_page.locator(".business-mark span")).to_have_text("05")
                for text in public_page.locator(".public-complaint-card .detail-cta").all_inner_texts():
                    assert text.strip() == "İncele →"
                for text in public_page.locator(".blog-card .detail-cta").all_inner_texts():
                    assert text.strip() == "Yazıyı Oku →"
                expect(public_page.get_by_text("Kategori belirtilmedi", exact=True)).to_have_count(0)
                no_overflow(public_page)

                user_page.goto(origin + "/hesap/profil/duzenle/", wait_until="networkidle")
                cards = user_page.locator(".profile-edit-card")
                expect(cards).to_have_count(2)
                expect(user_page.locator(".avatar-presets img")).to_have_count(20)
                boxes = [cards.nth(index).bounding_box() for index in range(2)]
                if width >= 1024:
                    ratio = boxes[0]["width"] / (boxes[0]["width"] + boxes[1]["width"])
                    assert 0.39 <= ratio <= 0.43, (width, ratio)
                else:
                    assert boxes[1]["y"] > boxes[0]["y"] + boxes[0]["height"] - 1
                no_overflow(user_page)

                if width in (375, 1440):
                    public_page.screenshot(path=str(output / f"homepage-{width}.png"), full_page=True)
                    user_page.screenshot(path=str(output / f"profile-edit-{width}.png"), full_page=True)
                report["viewports"].append({"width": width, "height": height, "overflow": False})

            assert not report["js_errors"], report["js_errors"]
            report["passed"] = True
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        (output / "results.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="dd-small-polish-qa-", ignore_cleanup_errors=True) as directory:
        run(directory)
