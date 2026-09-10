"""Auth V2 browser checks with Edge and an isolated, disposable database."""
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
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')


def run(directory):
    from django.conf import settings
    settings.DATABASES['default']['NAME'] = Path(directory) / 'qa.sqlite3'
    settings.MEDIA_ROOT = Path(directory) / 'media'
    import django
    django.setup()
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from accounts.models import User
    from companies.models import Company, CompanyCategory, CompanyMembership
    from playwright.sync_api import sync_playwright, expect

    call_command('migrate', verbosity=0)
    password = secrets.token_urlsafe(24)
    for role in ['USER', 'COMPANY', 'ADMIN']:
        account = User.objects.create_user(username='qa-' + role.lower(),
            email=role.lower() + '@example.com', password=password, user_type=role)
        if role == 'COMPANY':
            company = Company.objects.create(name='Kurumsal Deneyim', is_verified=True)
            CompanyMembership.objects.create(user=account, company=company, role='OWNER')
    category = CompanyCategory.objects.create(name='Teknoloji ve İletişim')
    for i in range(17):
        Company.objects.create(name=f'Deneyim Teknoloji {i + 1}', category=category,
            description='Açık iletişim ve çözüm odaklı hizmet sunan şirket.', is_verified=True)

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    server = make_server('127.0.0.1', 0, StaticFilesHandler(get_wsgi_application()), handler_class=QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = ROOT / 'docs/auth-v2-qa'
    output.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'viewports': [], 'role_matrix': [], 'checks': [], 'js_errors': []}
    routes = {'user-register': '/hesap/kayit/', 'user-login': '/hesap/giris/',
              'company-register': '/kurumsal/kayit/', 'company-login': '/kurumsal/giris/',
              'directory': '/sirketler/'}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            report['browser'] = browser.version
            context = browser.new_context()
            page = context.new_page()
            page.on('pageerror', lambda error: report['js_errors'].append(str(error)))

            def overflow_check():
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.url

            def fill(fields):
                for name, value in fields.items():
                    page.locator(f'[name="{name}"]').fill(value)

            def submit():
                page.locator('button[type="submit"]').click()
                page.wait_for_load_state()

            for width, height in [(375, 812), (430, 932), (768, 1024), (1024, 768), (1366, 768), (1440, 900)]:
                page.set_viewport_size({'width': width, 'height': height})
                for name, route in routes.items():
                    assert page.goto(origin + route).status == 200
                    overflow_check()
                    if name != 'directory':
                        assert page.locator('input:not([type=hidden])').evaluate_all('es => es.every(e => e.labels.length && e.getBoundingClientRect().right <= innerWidth)')
                        assert page.locator('[id]').evaluate_all('es => new Set(es.map(e => e.id)).size === es.length')
                        form = page.locator('.ax-form-area').bounding_box()
                        story = page.locator('.ax-story').bounding_box()
                        if width <= 768:
                            assert form['y'] < story['y']
                        else:
                            assert story['x'] < form['x']
                        button = page.locator('.ax-submit')
                        button.scroll_into_view_if_needed()
                        expect(button).to_be_in_viewport()
                        for toggle in page.locator('[data-password-toggle]').all():
                            control = page.locator('#' + toggle.get_attribute('aria-controls'))
                            toggle.click()
                            expect(control).to_have_attribute('type', 'text')
                            expect(toggle).to_have_attribute('aria-pressed', 'true')
                            toggle.click()
                            expect(control).to_have_attribute('type', 'password')
                    else:
                        expect(page.locator('.directory-card')).to_have_count(8)
                    page.evaluate('window.scrollTo(0,0)')
                    page.screenshot(path=str(output / f'{name}-{width}.png'), full_page=True)
                    report['viewports'].append({'width': width, 'page': name, 'overflow': False})

            page.goto(origin + '/sirketler/?s=Teknoloji&page=2')
            expect(page.locator('.directory-card')).to_have_count(8)
            expect(page.locator('.discovery-result strong')).to_have_text('17')
            assert 's=Teknoloji' in page.get_by_role('link', name='Sayfa 1', exact=True).get_attribute('href')
            report['checks'].append('Directory: 8 per page, page 2 and search query preserved')

            login_routes = {'USER': '/hesap/giris/', 'COMPANY': '/kurumsal/giris/', 'ADMIN': '/yonetim/giris/'}
            destinations = {'USER': '/panel/', 'COMPANY': '/sirket-panel/', 'ADMIN': '/yonetim/'}
            for source in login_routes:
                for target, route in login_routes.items():
                    context.clear_cookies()
                    page.goto(origin + route)
                    fill({('email' if target == 'COMPANY' else 'username'):
                          source.lower() + '@example.com' if target == 'COMPANY' else 'qa-' + source.lower(),
                          'password': password})
                    submit()
                    page.wait_for_url(origin + (destinations[target] if source == target else route))
                    if source != target:
                        assert page.locator('[role="alert"]').count() > 0
                        assert not page.locator('[name="password"]').input_value()
                    report['role_matrix'].append({'credentials': source, 'form': target, 'accepted': source == target})

            context.clear_cookies()
            page.set_viewport_size({'width': 375, 'height': 812})
            page.goto(origin + routes['user-register'])
            page.locator('form').evaluate('f => f.noValidate = true')
            fill({'username': 'bad username', 'email': 'invalid', 'password1': '123', 'password2': 'different'})
            submit()
            expect(page.locator('[data-auth-errors]')).to_be_focused()
            assert page.locator('[id]').evaluate_all('es => new Set(es.map(e => e.id)).size === es.length')
            assert page.locator('[aria-describedby]').evaluate_all('es => es.every(e => e.getAttribute("aria-describedby").split(" ").every(id => document.getElementById(id)))')
            overflow_check()
            page.screenshot(path=str(output / 'user-register-errors-375.png'), full_page=True)
            page.goto(origin + routes['user-register'])
            fill({'username': 'new-browser-user', 'email': 'new-browser-user@example.com', 'password1': password, 'password2': password})
            # Observe real submit state before navigation without delaying the request.
            page.locator('form').evaluate('f => f.addEventListener("submit", () => sessionStorage.setItem("qa-submit", JSON.stringify({disabled:f.querySelector("button[type=submit]").disabled,busy:f.getAttribute("aria-busy")})))')
            submit()
            page.wait_for_url(origin + '/panel/')
            assert json.loads(page.evaluate('sessionStorage.getItem("qa-submit")')) == {'disabled': True, 'busy': 'true'}
            report['checks'].append('USER registration succeeds; labels, unique error IDs, descriptions, error focus, password toggles and submit loading verified')

            context.clear_cookies()
            page.goto(origin + routes['company-register'])
            fill({'company_name': 'Browser Başvurusu', 'first_name': 'Deniz', 'last_name': 'Yılmaz',
                  'email': 'browser-application@example.com', 'phone': '5551234567', 'password1': password, 'password2': password})
            submit()
            page.wait_for_url(origin + routes['company-login'])
            expect(page.locator('.ax-application-success')).to_be_visible()
            overflow_check()
            page.screenshot(path=str(output / 'company-application-success-375.png'), full_page=True)
            fill({'email': 'browser-application@example.com', 'password': password})
            submit()
            expect(page.locator('[data-auth-errors]')).to_be_focused()
            page.screenshot(path=str(output / 'company-login-errors-375.png'), full_page=True)
            report['checks'].append('COMPANY registration shows approval confirmation; pending application cannot log in')
            admin_context = browser.new_context()
            admin_page = admin_context.new_page()
            admin_page.goto(origin + '/yonetim/giris/')
            admin_page.locator('[name=username]').fill('qa-admin')
            admin_page.locator('[name=password]').fill(password)
            admin_page.locator('button[type=submit]').click()
            admin_page.wait_for_url(origin + '/yonetim/')
            admin_page.goto(origin + '/yonetim/sirket-basvurulari/')
            admin_page.get_by_role('link', name='Browser Başvurusu başvurusunu incele', exact=True).click()
            admin_page.get_by_role('button', name='Onayla', exact=True).click()
            expect(admin_page.get_by_text('Şirket başvurusu onaylandı.', exact=True)).to_be_visible()
            admin_context.close()
            fill({'email': 'browser-application@example.com', 'password': password})
            submit()
            page.wait_for_url(origin + '/sirket-panel/')
            report['checks'].append('Same newly registered COMPANY can log in after real ADMIN approval')
            context.clear_cookies()
            for name in ['user-login', 'company-login']:
                page.goto(origin + routes[name])
                cross = page.locator('.ax-crosslink a')
                expected = routes['company-login' if name == 'user-login' else 'user-login']
                assert cross.get_attribute('href') == expected
                cross.click()
                page.wait_for_url(origin + expected)
            report['checks'].append('USER/COMPANY login cross-links work')

            nojs = browser.new_context(java_script_enabled=False)
            plain = nojs.new_page()
            plain.goto(origin + routes['user-login'])
            assert not plain.locator('[data-password-toggle]').is_visible()
            plain.locator('[name=username]').fill('new-browser-user')
            plain.locator('[name=password]').fill(password)
            plain.locator('button[type=submit]').click()
            plain.wait_for_url(origin + '/panel/')
            report['checks'].append('Login works without JavaScript')
            nojs.close()
            assert not report['js_errors'], report['js_errors']
            report['passed'] = True
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        from django.db import connections
        connections.close_all()
        (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='dertderman-auth-qa-') as directory:
        run(directory)
