"""Run public grid, reader and archive QA in Edge with a disposable database.

Usage: python scripts/qa_public_archive.py (Playwright and Edge required).
Screenshots and machine-readable assertions go to docs/public-archive-qa.
"""
import json
from contextlib import closing
import os
from pathlib import Path
import secrets
import sqlite3
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
    from django.utils import timezone
    from accounts.models import User
    from companies.models import Company, CompanyCategory, CompanyMembership
    from complaints.models import Complaint
    from blog.models import Post
    from playwright.sync_api import sync_playwright, expect

    call_command('migrate', verbosity=0)
    password = secrets.token_urlsafe(24)
    admin = User.objects.create_user(username='qa-admin', email='qa-admin@example.com',
                                    password=password, user_type='ADMIN')
    reader = User.objects.create_user(username='qa-reader', email='qa-reader@example.com')
    agent = User.objects.create_user(username='qa-company', email='qa-company@example.com', user_type='COMPANY')
    category = CompanyCategory.objects.create(name='Teknoloji ve İletişim')
    companies = []
    for i in range(17):
        company = Company.objects.create(name=f'İletişim Teknoloji {i + 1}', category=category,
            description='Müşteri deneyimlerini dinleyen, açık iletişim ve çözüm odaklı hizmet sunan şirket.',
            is_verified=i % 2 == 0)
        companies.append(company)
        CompanyMembership.objects.create(company=company, user=agent, role='OWNER')
        Complaint.objects.create(company=company, user=reader, title=f'Deneyim {i}',
                                 description='Geçmiş şikayet kaydı.', status='PUBLISHED')
    posts = []
    for i in range(13):
        posts.append(Post.objects.create(title=f'Tüketici deneyimi rehberi {i + 1}', author=admin,
            excerpt='Başvuru, iletişim ve takip süreçlerini daha iyi anlamak için pratik bilgiler.',
            content='\n\n'.join(f'{n + 1}. Deneyiminizi açık bir dille anlatın. Başvuru bilgilerinizi saklayın ve süreci takip edin.' for n in range(24)),
            status='PUBLISHED', published_at=timezone.now()))
    for status in ['PENDING', 'REJECTED']:
        Company.objects.create(name=f'Gizli {status}', approval_status=status)
    Company.objects.create(name='Gizli pasif', is_active=False)
    Company.objects.create(name='Gizli arşiv', archived_at=timezone.now())
    for status in ['DRAFT', 'ARCHIVED']:
        Post.objects.create(title=f'Gizli {status}', excerpt='Gizli özet', content='Gizli içerik', status=status)

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    server = make_server('127.0.0.1', 0, StaticFilesHandler(get_wsgi_application()), handler_class=QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    output = ROOT / 'docs' / 'public-archive-qa'
    output.mkdir(parents=True, exist_ok=True)
    report = {'viewports': [], 'checks': [], 'js_errors': [], 'passed': False}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            report['browser'] = browser.version
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            page = context.new_page()
            page.on('pageerror', lambda error: report['js_errors'].append(str(error)))

            def no_overflow():
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

            def open_article(preserve_scroll=False):
                link = page.locator('.journal-card-image').first
                if preserve_scroll:
                    box = link.bounding_box()
                    page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                else:
                    link.click()
                expect(page.locator('#article-reader [data-reader-article]')).to_be_visible()
                assert page.locator('[data-reader-close]').evaluate('e => e === document.activeElement')
                assert page.evaluate("getComputedStyle(document.body).position === 'fixed'")
                return link

            def close_article(link, method='button'):
                if method == 'escape':
                    page.keyboard.press('Escape')
                elif method == 'backdrop':
                    page.mouse.click(2, 2)
                else:
                    page.get_by_role('button', name='Yazıyı kapat').click()
                expect(page.locator('#article-reader')).not_to_be_visible()
                page.wait_for_url(origin + '/blog/')
                # History traversal restores scroll after the URL changes.
                page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                assert link.evaluate('e => e === document.activeElement')
                assert page.evaluate("!document.body.classList.contains('reader-open')")

            # Authenticate only the disposable QA account through the real form.
            page.goto(origin + '/yonetim/giris/')
            page.get_by_label('Kullanıcı adı', exact=True).fill('qa-admin')
            page.get_by_label('Şifre', exact=True).fill(password)
            page.get_by_role('button', name='Giriş Yap', exact=True).click()
            page.wait_for_url(origin + '/yonetim/')

            for width, height in [(375, 812), (430, 932), (768, 1024), (1024, 768), (1366, 768), (1440, 900)]:
                page.set_viewport_size({'width': width, 'height': height})
                row = {'width': width, 'height': height}
                for route, grid, size in [('/sirketler/', 'directory', 8), ('/blog/', 'journal', 6)]:
                    assert page.goto(origin + route).status == 200
                    expect(page.locator(f'.{grid}-card')).to_have_count(size)
                    no_overflow()
                    columns = page.locator(f'.{grid}-grid').evaluate('e => getComputedStyle(e).gridTemplateColumns.split(" ").length')
                    assert columns == (1 if width < 768 else 2 if width < 1200 else 4 if grid == 'directory' else 3)
                    row[grid + '_columns'] = columns
                    page.screenshot(path=str(output / f'{grid}-{width}.png'), full_page=True)
                    page.get_by_role('link', name='Sayfa 2', exact=True).click()
                    expect(page.locator(f'.{grid}-card')).to_have_count(size)
                    assert 'page=2' in page.url
                    no_overflow()
                page.goto(origin + '/blog/')
                link = open_article()
                no_overflow()
                box = page.locator('#article-reader').bounding_box()
                if width < 768:
                    assert box['x'] == 0 and box['y'] == 0
                    assert box['width'] == width and box['height'] == height
                assert page.locator('[data-reader-scroll]').evaluate('e => e.scrollHeight > e.clientHeight')
                page.screenshot(path=str(output / f'reader-{width}.png'))
                close_article(link, 'escape')
                for route, action in [('/yonetim/blog/', 'blog'), ('/yonetim/sirketler/', 'company')]:
                    page.goto(origin + route)
                    expect(page.locator('tbody tr')).to_have_count(5)
                    button = page.locator('[data-confirm-action]').first
                    button.click()
                    expect(page.locator('#admin-confirm')).to_be_visible()
                    no_overflow()
                    assert page.locator('#admin-confirm').evaluate('e => e.scrollWidth <= e.clientWidth')
                    page.screenshot(path=str(output / f'{action}-confirm-{width}.png'))
                    page.get_by_role('button', name='Vazgeç', exact=True).click()
                    expect(page.locator('#admin-confirm')).not_to_be_visible()
                    assert button.evaluate('e => e === document.activeElement')
                row['overflow'] = False
                row['modal_and_confirmations'] = True
                report['viewports'].append(row)

            page.goto(origin + '/blog/')
            link = open_article()
            close_article(link, 'backdrop')
            link = open_article()
            close_article(link)
            page.evaluate("window.scrollTo({top: 450, behavior: 'instant'})")
            scroll_before = page.evaluate('scrollY')
            link = open_article(preserve_scroll=True)
            assert page.evaluate('parseFloat(document.body.style.top)') == -scroll_before, {
                'before': scroll_before, 'locked_top': page.evaluate('document.body.style.top'),
            }
            page.keyboard.press('Shift+Tab')
            assert page.locator('#article-reader').evaluate('e => e.contains(document.activeElement)')
            close_article(link)
            page.wait_for_function('before => Math.abs(scrollY - before) < 2', arg=scroll_before)
            link = open_article()
            page.go_back()
            expect(page.locator('#article-reader')).not_to_be_visible()
            page.go_forward()
            expect(page.locator('#article-reader [data-reader-article]')).to_be_visible()
            close_article(link)
            report['checks'].append('Reader: content, ESC, close, backdrop, focus, focus containment, scroll lock/restore, browser back/forward')

            # Failed content requests keep a usable direct detail link.
            article_url = origin + page.locator('.journal-card-image').first.get_attribute('href')
            page.route(article_url, lambda route: route.fulfill(status=503, body='Unavailable'))
            page.locator('.journal-card-image').first.click()
            expect(page.locator('.reader-error a')).to_have_attribute('href', article_url)
            close_article(page.locator('.journal-card-image').first)
            page.unroute(article_url)
            report['checks'].append('Reader error state includes direct detail fallback')

            for route, label, term, size in [('/sirketler/', 'Şirket veya kategori ara', 'İletişim', 8),
                                            ('/blog/', 'Yazılarda ara', 'rehberi', 6)]:
                page.goto(origin + route)
                page.get_by_label(label, exact=True).fill(term)
                page.get_by_role('button', name='Ara', exact=True).click()
                page.get_by_role('link', name='Sayfa 2', exact=True).click()
                assert 's=' in page.url and 'page=2' in page.url
                expect(page.locator('.directory-card, .journal-card')).to_have_count(size)
                page.get_by_label(label, exact=True).fill('bulunamayan-kayit')
                page.get_by_role('button', name='Ara', exact=True).click()
                expect(page.locator('.discovery-empty')).to_be_visible()
            report['checks'].append('Both searches preserve queries on page 2 and render empty states')

            nojs = browser.new_context(java_script_enabled=False, viewport={'width': 375, 'height': 812})
            fallback = nojs.new_page()
            fallback.goto(origin + '/blog/')
            fallback.locator('.journal-card-image').first.click()
            expect(fallback.locator('[data-reader-article]')).to_be_visible()
            expect(fallback.locator('#article-reader')).to_have_count(0)
            assert fallback.locator('link[rel="canonical"]').get_attribute('href') == fallback.url
            fallback.screenshot(path=str(output / 'direct-nojs-375.png'), full_page=True)
            nojs.close()
            report['checks'].append('JavaScript disabled: card navigates to full direct article with canonical URL')

            # Final destructive clicks affect fixture rows only.
            page.goto(origin + '/yonetim/blog/?status=PUBLISHED')
            page.locator('[data-confirm-action]').first.click()
            with page.expect_response(lambda r: r.request.method == 'POST' and '/sil/' in r.url) as response:
                page.get_by_role('button', name='Evet, yazıyı sil', exact=True).click()
            assert response.value.status == 302
            with closing(sqlite3.connect(settings.DATABASES['default']['NAME'])) as database:
                assert database.execute('SELECT status FROM blog_post WHERE id = ?', [posts[-1].pk]).fetchone() == ('ARCHIVED',)
            assert page.goto(origin + '/blog/' + posts[-1].slug + '/').status == 404
            page.goto(origin + '/yonetim/blog/?status=ARCHIVED')
            expect(page.get_by_role('cell', name=posts[-1].title, exact=True)).to_be_visible()
            page.goto(origin + '/yonetim/sirketler/?q=' + companies[-1].name)
            page.locator('[data-confirm-action]').first.click()
            with page.expect_response(lambda r: r.request.method == 'POST' and '/arsivle/' in r.url) as response:
                page.get_by_role('button', name='Evet, şirketi arşivle', exact=True).click()
            assert response.value.status == 302
            expect(page.locator('.ad-archive-notice')).to_be_visible()
            with closing(sqlite3.connect(settings.DATABASES['default']['NAME'])) as database:
                archived_at, active = database.execute('SELECT archived_at, is_active FROM companies_company WHERE id = ?', [companies[-1].pk]).fetchone()
                assert archived_at and not active
                for table in ['complaints_complaint', 'companies_companymembership']:
                    assert database.execute(f'SELECT COUNT(*) FROM {table} WHERE company_id = ?', [companies[-1].pk]).fetchone() == (1,)
            report['checks'].append('Blog/company confirm sends POST with valid CSRF; archive state, archive filter and complaint/membership preservation verified')
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
    with tempfile.TemporaryDirectory(prefix='dertderman-public-qa-') as directory:
        run(directory)
