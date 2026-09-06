# Homepage hero ve custom yönetim başlangıcı

Hero'nun sağındaki eski açıklamalı SVG kartları ve küçük alt metin kaldırıldı. Yerine DertDerman’a hoş geldiniz / Derdinizi anlatın / Sesiniz duyulsun / Dertten dermana mesajları ve özgün inline SVG bağlantı çizgisi eklendi.

Masaüstünde satırlar 18 px soldan, transform/opacity ile 900 ms'de girer; satır başlangıçları 180 ms aralıklıdır. Animasyon bir kez çalışır, toplam 1440 ms'de tamamlanır. Mevcut IntersectionObserver görünürlük/sekme kontrolleri kullanılır; yeni JS veya bağımlılık eklenmedi. Mobilde ve reduced-motion altında statiktir; JS olmadan tüm içerik görünürdür.

## Yönetim kapsamı

`/yonetim/` artık beş alanı sade yatay satırlar ve ortak yönetim navigasyonuyla sunar:

| Alan | Mevcut yetenek |
| --- | --- |
| Şikayetler | Mevcut inceleme listesi, detay, yayınlama/reddetme |
| Blog yazıları | Mevcut liste, taslak oluşturma, düzenleme, yayınlama |
| Şirketler | Yeni 20 kayıt/sayfa liste ve tanıtım/iletişim düzenleme |
| Kullanıcılar | Yeni 20 kayıt/sayfa salt okunur hesap, e-posta, rol, aktiflik listesi |
| Ana sayfa içerikleri | Yeni salt okunur hero mesajları önizlemesi |

Şirket formunda yalnızca name, description, website, email, phone kaydedilir. Slug, aktiflik, doğrulama ve membership değişiklikleri sunulmaz; gönderilen ekstra alanlar kaydedilmez. User rol/yetki düzenleme bu sürümde yoktur. Hero mesajları `core/presentation.py` içindeki tek kaynaktan hem public hero'ya hem admin önizlemesine gelir; panelden metin düzenleme henüz sunulmaz. Bu turda model veya migration eklenmedi.

Yeni yollar: `/yonetim/sirketler/`, `/yonetim/sirketler/<pk>/duzenle/`, `/yonetim/kullanicilar/`, `/yonetim/ana-sayfa/`.

## Güvenlik ve test

- Tüm yeni view'lar `role_required(ADMIN)` ile korunur. Anonim yönlendirme, USER/COMPANY/UNKNOWN için 403, ADMIN için 200 + no-store test edildi.
- Şirket kaydı yalnızca CSRF korumalı POST ile değiştirilir. Yetkisiz POST, eksik CSRF, ek alan manipülasyonu, olmayan nesne ve logout sonrası eski session replay kontrolleri geçti.
- Kullanıcı/ana sayfa/list view'ları salt okunurdur; POST için 405 döner.
- Mevcut `/django-admin/` custom 404, catch-all, media, role, session, IDOR, CSRF ve private cache testleri korundu. Publication selector değiştirilmedi.
- `python manage.py check`: sorun yok.
- `python manage.py test`: **135 test geçti** (önceki 130 + 5 yeni içerik yönetimi testi).
- `python manage.py makemigrations --check --dry-run`: **No changes detected**.
- Headless Chromium QA: 49 ekran/durum × 320, 360, 768, 1024, 1440 px = **245 kontrol**. Yatay taşma, JS hatası, static/media asset hatası, dış istek, yinelenen asset veya eksik form label/description referansı yok.
- Hero'nun tek seferlik animasyonu, mobil/reduced-motion/no-JS hali ve görünürlük durdurması; mevcut auth, count-up, lifecycle, feedback ve error ekranları kontrol edildi. Count-up CLS 0; homepage sorgu sayısı 6 olarak kaldı. JavaScript 8314 byte ile değişmedi.
- QA çıktıları: `C:/Users/hdgn5/AppData/Local/Temp/dd-ui-hero-admin-qa/`.

## Değişen dosyalar

- `core/presentation.py` (yeni)
- `core/views.py`
- `adminx/content_views.py` (yeni)
- `adminx/forms.py` (yeni)
- `adminx/test_content.py` (yeni)
- `adminx/urls.py`
- `templates/home.html`
- `templates/components/hero_brand.html` (yeni)
- `templates/components/workspace_nav.html`
- `templates/adminx/home.html`
- `templates/adminx/content_base.html` (yeni)
- `templates/adminx/content_pagination.html` (yeni)
- `templates/adminx/company_list.html` (yeni)
- `templates/adminx/company_form.html` (yeni)
- `templates/adminx/user_list.html` (yeni)
- `templates/adminx/homepage_content.html` (yeni)
- `static/css/pages.css`
- `static/css/motion.css`
- `HERO_ADMIN_REPORT.md` (yeni)
