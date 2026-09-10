"""Notification center UI and workflow QA with a disposable database and Edge."""
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
    from companies.models import Company, CompanyMembership
    from complaints.models import Complaint
    from playwright.sync_api import sync_playwright, expect

    call_command('migrate', verbosity=0)
    password = secrets.token_urlsafe(24)
    accounts = {}
    for role in ['USER', 'COMPANY', 'ADMIN']:
        accounts[role] = User.objects.create_user(username='qa-' + role.lower(),
            email=role.lower() + '@example.com', password=password, user_type=role)
    company = Company.objects.create(name='Deneyim İletişim', is_verified=True)
    CompanyMembership.objects.create(user=accounts['COMPANY'], company=company, role='OWNER')
    for i in range(13):
        complaint = Complaint.objects.create(user=accounts['USER'], company=company,
            title=f'İletişim deneyimim hakkında {i + 1}', description='Başvurumun incelenmesini ve çözüm süreci hakkında bilgi verilmesini istiyorum.')
        if i % 3 == 0:
            complaint.status = 'PUBLISHED'
            complaint.save()
    for i in range(3):
        Company.objects.create(name=f'Yeni Şirket Başvurusu {i + 1}', approval_status='PENDING', is_active=False)
    for role in accounts:
        empty_user = User.objects.create_user(username='empty-' + role.lower(),
            email='empty-' + role.lower() + '@example.com', password=password, user_type=role)
        if role == 'COMPANY':
            empty_company = Company.objects.create(name='Yeni Çalışma Alanı', is_verified=True)
            CompanyMembership.objects.create(user=empty_user, company=empty_company, role='OWNER')

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    server = make_server('127.0.0.1', 0, StaticFilesHandler(get_wsgi_application()), handler_class=QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = ROOT / 'docs/notification-qa'
    output.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'screens': [], 'checks': [], 'js_errors': []}
    routes = {'USER': '/bildirimler/', 'COMPANY': '/sirket-panel/bildirimler/', 'ADMIN': '/yonetim/bildirimler/'}
    logins = {'USER': '/hesap/giris/', 'COMPANY': '/kurumsal/giris/', 'ADMIN': '/yonetim/giris/'}
    homes = {'USER': '/panel/', 'COMPANY': '/sirket-panel/', 'ADMIN': '/yonetim/'}
    rows = {'USER': '.nc-item', 'COMPANY': '.cp-notification', 'ADMIN': '.nc-admin-row'}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            report['browser'] = browser.version
            context = browser.new_context()
            page = context.new_page()
            page.on('pageerror', lambda error: report['js_errors'].append(str(error)))

            def login(role, empty=False):
                context.clear_cookies()
                page.goto(origin + logins[role])
                prefix = 'empty-' if empty else 'qa-'
                identifier = ('empty-' if empty else '') + role.lower() + '@example.com' if role == 'COMPANY' else prefix + role.lower()
                page.locator('[name=email]' if role == 'COMPANY' else '[name=username]').fill(identifier)
                page.locator('[name=password]').fill(password)
                page.locator('button[type=submit]').click()
                page.wait_for_url(origin + homes[role])

            def no_overflow():
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.url

            for role, route in routes.items():
                login(role)
                for width, height in [(375, 812), (430, 932), (768, 1024), (1024, 768), (1366, 768), (1440, 900)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    assert page.goto(origin + route).status == 200
                    expect(page.locator(rows[role])).to_have_count(10 if role == 'ADMIN' else 8)
                    no_overflow()
                    assert page.get_by_role('link', name='Bildirimler', exact=False).count() >= 1
                    page.screenshot(path=str(output / f'{role.lower()}-{width}.png'), full_page=True)
                    report['screens'].append({'role': role, 'width': width, 'overflow': False})
                page.get_by_role('link', name='Sayfa 2', exact=True).click()
                assert 'page=2' in page.url
                assert page.locator(rows[role]).count() > 0
                no_overflow()
                page.goto(origin + route)
                first = page.locator(rows[role]).first
                first.get_by_role('button', name='Okundu işaretle', exact=True).click()
                page.wait_for_url(origin + route)
                page.get_by_role('button', name='Tümünü okundu işaretle', exact=True).click()
                page.wait_for_url(origin + route)
                expect(page.get_by_role('button', name='Tümünü okundu işaretle', exact=True)).to_be_disabled()
                expect(page.locator(rows[role] + '.is-unread')).to_have_count(0)
                report['checks'].append(role + ': page 2, single-read, mark-all and unread badge update')
                login(role, empty=True)
                page.goto(origin + route)
                expect(page.locator(rows[role])).to_have_count(0)
                page.set_viewport_size({'width': 375, 'height': 812})
                no_overflow()
                page.screenshot(path=str(output / f'{role.lower()}-empty-375.png'), full_page=True)

            # Three required scenarios run through actual application forms.
            login('USER')
            page.goto(origin + '/sikayet-olustur/')
            page.locator('[name=company]').select_option(str(company.pk))
            page.locator('[name=title]').fill('Tarayıcı olay akışı')
            page.locator('[name=description]').fill('Bu başvuruyu tarayıcı üzerinden oluşturup yönetim ve şirket yanıtını kontrol ediyorum.')
            page.locator('button[type=submit]').filter(has_text='Gönder').click()
            page.wait_for_url(origin + '/panel/')
            page.goto(origin + routes['USER'])
            expect(page.locator('.nc-item').first).to_contain_text('Şikayetiniz alındı.')

            login('ADMIN')
            page.goto(origin + routes['ADMIN'])
            item = page.locator('.nc-admin-row').filter(has_text='Tarayıcı olay akışı')
            expect(item).to_have_count(1)
            item.get_by_role('link', name='İncele ↗', exact=True).click()
            page.get_by_role('button', name='Yayınla', exact=True).click()
            login('USER')
            page.goto(origin + routes['USER'])
            expect(page.locator('.nc-item').first).to_contain_text('Şikayetiniz yayınlandı.')
            report['checks'].append('USER complaint published -> owner USER notification')

            login('COMPANY')
            page.goto(origin + routes['COMPANY'])
            page.locator('.cp-notification').first.get_by_role('link', name='Şikayeti incele', exact=False).click()
            page.locator('#response [name=body]').fill('Başvurunuzu inceledik. Çözüm için sizinle iletişime geçeceğiz.')
            page.get_by_role('button', name='Cevabı kaydet', exact=False).click()
            login('USER')
            page.goto(origin + routes['USER'])
            item = page.locator('.nc-item').first
            expect(item).to_contain_text('Şirket şikayetinize cevap verdi.')
            item.get_by_role('link', name='İlgili sayfaya git', exact=False).click()
            expect(page.get_by_text('Başvurunuzu inceledik. Çözüm için sizinle iletişime geçeceğiz.', exact=True)).to_be_visible()
            report['checks'].append('COMPANY response -> owner USER notification -> own detail shows response')

            context.clear_cookies()
            page.goto(origin + '/kurumsal/kayit/')
            for name, value in {'company_name': 'Tarayıcı Kurumsal Başvurusu', 'first_name': 'Deniz', 'last_name': 'Yılmaz',
                                'email': 'browser-notification@example.com', 'phone': '5551234567', 'password1': password, 'password2': password}.items():
                page.locator(f'[name={name}]').fill(value)
            page.get_by_role('button', name='Başvuruyu Gönder', exact=True).click()
            page.wait_for_url(origin + '/kurumsal/giris/')
            login('ADMIN')
            page.goto(origin + routes['ADMIN'])
            item = page.locator('.nc-admin-row').first
            expect(item).to_contain_text('Yeni şirket başvurusu.')
            expect(item).to_contain_text('Tarayıcı Kurumsal Başvurusu')
            item.get_by_role('link', name='İncele ↗', exact=True).click()
            expect(page.get_by_role('heading', name='Tarayıcı Kurumsal Başvurusu', exact=True)).to_be_visible()
            report['checks'].append('New company application -> ADMIN notification -> application detail')
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
    with tempfile.TemporaryDirectory(prefix='dertderman-notifications-qa-') as directory:
        run(directory)
