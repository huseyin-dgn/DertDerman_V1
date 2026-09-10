"""USER experience browser checks with Edge and a disposable database."""
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
    from complaints.models import Complaint
    from notifications.models import Notification
    from playwright.sync_api import sync_playwright

    call_command("migrate", verbosity=0)
    password = secrets.token_urlsafe(24)
    user = User.objects.create_user(
        username="qa-consumer",
        email="consumer@example.com",
        password=password,
        first_name="Deniz",
        last_name="Yılmaz",
        phone="0555 123 45 67",
        user_type="USER",
    )
    company = Company.objects.create(name="QA Teknoloji", is_verified=True)
    agent = User.objects.create_user(username="qa-company-agent", email="qa-agent@example.com", user_type="COMPANY")
    CompanyMembership.objects.create(user=agent, company=company, role="OWNER")
    statuses = ["PENDING", "PUBLISHED", "RESOLVED", "REJECTED"]
    complaints = [Complaint.objects.create(
        user=user, company=company, status=statuses[index % len(statuses)],
        title=f"QA panel şikayeti {index:02d}",
        description="Responsive kullanıcı paneli kontrolü için yeterince uzun örnek açıklama.",
    ) for index in range(13)]
    CompanyResponse.objects.create(company=company, complaint=complaints[1], author_user=agent,
                                   body="Şirket çözüm için kullanıcıyla iletişime geçti.")
    Notification.objects.create(
        recipient_user=user,
        recipient_role="USER",
        notification_type="UPDATED",
        title="Süreç güncellendi",
        message="Şikayet sürecinizde yeni bir gelişme var.",
        event_key="qa-user-experience",
    )

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    server = make_server(
        "127.0.0.1",
        0,
        StaticFilesHandler(get_wsgi_application()),
        handler_class=QuietHandler,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    output = ROOT / "docs/user-experience-qa"
    output.mkdir(parents=True, exist_ok=True)
    widths = [(375, 812), (430, 932), (768, 1024), (1024, 768), (1366, 768), (1440, 900)]
    routes = ["/", "/panel/", "/sikayetlerim/", "/bildirimler/", "/hesap/profil/", "/sikayet-olustur/"]
    expected_main = ["Ana Sayfa", "Şikayetler", "Şirketler", "Blog"]
    expected_actions = ["Profilim", "Bildirimler", "Şikayet Yaz", "Çıkış"]
    expected_tabs = ["Genel Bakış", "Şikayetlerim", "Bildirimler", "Hesabım"]
    report = {"passed": False, "browser": None, "viewports": [], "checks": [], "js_errors": []}

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            report["browser"] = browser.version
            context = browser.new_context()
            page = context.new_page()
            page.on("pageerror", lambda error: report["js_errors"].append(str(error)))
            page.goto(origin + "/hesap/giris/")
            page.locator("[name=username]").fill(user.username)
            page.locator("[name=password]").fill(password)
            page.locator("button[type=submit]").click()
            page.wait_for_url(origin + "/panel/")

            for width, height in widths:
                page.set_viewport_size({"width": width, "height": height})
                for route in routes:
                    if route == "/":
                        page.evaluate("sessionStorage.setItem('dd_intro_returning', '1')")
                    assert page.goto(origin + route).status == 200
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, route)
                    toggle = page.locator("[data-nav-toggle]")
                    if width <= 1180:
                        assert toggle.is_visible()
                        toggle.click()
                    else:
                        assert not toggle.is_visible()

                    header = page.locator(".site-header")
                    assert header.locator(".nav-main a").all_inner_texts() == expected_main
                    actions = header.locator(".nav-actions")
                    labels = actions.locator(":scope > a, :scope > form > button").all_inner_texts()
                    labels = [" ".join(label.split()) for label in labels]
                    assert labels[0] == expected_actions[0] and labels[1].startswith(expected_actions[1])
                    assert labels[2:] == expected_actions[2:], (width, route, labels)
                    header_text = header.inner_text()
                    for forbidden in ["Panelim", "Kurumsal", "Şirket Girişi", "Şirket Kaydı", "Yönetim"]:
                        assert forbidden not in header_text

                    action_boxes = actions.locator(":scope > a, :scope > form > button").evaluate_all(
                        "els => els.map(el => ({height: el.getBoundingClientRect().height, left: el.getBoundingClientRect().left, right: el.getBoundingClientRect().right}))"
                    )
                    assert max(box["height"] for box in action_boxes) - min(box["height"] for box in action_boxes) < 1, (width, route, action_boxes)
                    badge = actions.locator(".nc-count")
                    assert badge.count() == 1
                    assert badge.evaluate("el => { const b=el.getBoundingClientRect(), p=el.parentElement.getBoundingClientRect(); return b.left >= p.left && b.right <= p.right && b.top >= p.top && b.bottom <= p.bottom; }")

                    if route != "/":
                        tabs = page.locator(".workspace-nav a")
                        assert tabs.all_inner_texts() == expected_tabs
                        assert page.locator(".workspace-nav a[aria-current=page]").count() == 1

                page.goto(origin + "/hesap/profil/")
                if width <= 1180:
                    page.locator("[data-nav-toggle]").click()
                profile_text = page.locator(".profile-card").inner_text()
                for required in ["Deniz Yılmaz", "consumer@example.com", "0555 123 45 67", "Katılım tarihi", "Bilgilerimi Düzenle", "Şifre Değiştir", "Ana Sayfa"]:
                    assert required in profile_text
                for forbidden in ["Hesap türü", "Hesap durumu", "Siteye Dön", "USER"]:
                    assert forbidden not in profile_text
                page.screenshot(path=str(output / f"profile-{width}.png"), full_page=True)
                report["viewports"].append({"width": width, "routes": len(routes), "overflow": False})

                visual_routes = {
                    "dashboard": "/panel/",
                    "complaints": "/sikayetlerim/?q=QA",
                    "profile-edit": "/hesap/profil/duzenle/",
                    "timeline": f"/sikayetlerim/{complaints[1].pk}/",
                }
                for name, route in visual_routes.items():
                    assert page.goto(origin + route).status == 200
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, route)
                    assert page.locator("button, a").evaluate_all(
                        "els => els.filter(el => el.offsetParent !== null && !el.closest('.user-filter-tabs')).every(el => { const r=el.getBoundingClientRect(); return r.left >= -1 && r.right <= document.documentElement.scrollWidth + 1; })"
                    )
                    if name == "dashboard":
                        assert page.locator(".user-metric").count() == 5
                    elif name == "complaints":
                        assert page.locator(".user-complaint-card").count() == 6
                        assert page.locator(".dd-pagination").count() == 1
                        assert "q=QA" in page.locator(".dd-pagination a").first.get_attribute("href")
                    elif name == "profile-edit":
                        assert page.locator(".profile-edit-form input:not([type=hidden])").count() == 4
                    elif name == "timeline":
                        assert page.locator(".timeline-event").count() >= 3
                    page.screenshot(path=str(output / f"{name}-{width}.png"), full_page=True)

            assert not report["js_errors"], report["js_errors"]
            report["checks"] = [
                "Six USER routes share the requested navbar and hide corporate/admin entries",
                "Navbar action heights and notification badge bounds are consistent",
                "USER subnav order, active state and responsive layout are valid",
                "Profile V2 content and actions are consumer-focused",
            ]
            report["passed"] = True
            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        from django.db import connections

        connections.close_all()
        (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="dertderman-user-ux-qa-") as directory:
        run(directory)
