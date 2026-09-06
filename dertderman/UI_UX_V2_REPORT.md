# DertDerman UI V2 + UX States / Blog V1

## Existing Redesign Preservation

Redesign sırasında oluşturulan mavi/beyaz, soft-blue/navy sistem korundu. Sonraki UX/blog isteği bu sistemin üzerine uygulandı; ikinci bir CSS sistemi veya ikinci navbar oluşturulmadı. Mevcut ürün veritabanına örnek kullanıcı, şirket, şikayet veya blog içeriği eklenmedi. Test verileri yalnızca ayrı Django test veritabanında kullanıldı.

## UI Audit

Önceki arayüzde auth tek dar karttan oluşuyordu; kullanıcı paneli profil formuna benziyordu. Public şirket listesi düz listeydi, şirket panelleri ortak layout kullanmıyordu. Tek CSS dosyası sayfa ve component kurallarını karıştırıyordu; mobil navigasyon, motion ve ortak form hata yapısı eksikti.

| Ekran grubu | Template envanteri | Ortak bileşenler |
| --- | --- | --- |
| Ana sayfa | `home.html` | Brand, solution visual, complaint/company/blog kartları |
| Auth | `accounts/login.html`, `register.html` | Auth story, BoundField, brand |
| USER | `dashboard/home.html`, `accounts/profile.html`, `profile_edit.html`, `password_change.html` | Workspace nav, identity, account panel, form fields |
| Private complaint | `complaints/complaint_create.html`, `complaint_list.html`, `complaint_detail.html` | Workspace, mini list, status badge, form fields |
| Public complaint | `complaints/public_list.html`, `public_detail.html`, `public_card.html` | Public cards, status badge, reading panel |
| Company | `companies/company_list.html`, `company_detail.html`, `company_dashboard.html`, `company_panel_detail.html` | Company card/identity, workspace |
| Custom admin | `adminx/home.html`, `complaint_list.html`, `complaint_detail.html` | Workspace, operating panels, status/actions |
| Blog | `blog/post_list.html`, `post_detail.html`, `card.html`, `status_badge.html` | Editorial cards, pagination, reading width |
| Admin blog | `adminx/blog_list.html`, `blog_form.html` | Workspace, fields, safe cover widget, publish panel |
| Errors | `400.html`, `403.html`, `404.html`, `500.html`, `csrf_failure.html` | Error SVG, public-safe actions |

Blog/notifications/payments ile eski admin placeholder template'lerinin boş ve route'a bağlı olmayanları ürün ekranı olarak sunulmadı. Yeni blog route'ları ayrıca eklendi.

## Design System

- `tokens.css`: renk, spacing, font, radius ve shadow değişkenleri.
- `base.css`: typography, semantic defaults, focus, skip link ve container.
- `components.css`: navbar, buttons, cards, fields, status ve feedback.
- `pages.css`: hero, auth split layout, workspace, reading ve blog düzenleri.
- `motion.css`: tek seferlik transform/opacity animasyonları ve reduced motion.

Primary `#1D5FA7`, navy `#102A43`, body `#243B53`, muted `#526B82`, soft surface `#EEF5FB`. Remote font yok; system font stack kullanılır. Primary/secondary/ghost/danger/text action türleri; 44–52 px dokunma hedefleri; ortak spacing ve 8/16/24 px radius ölçeği vardır. Complaint/company/auth/account/admin kartları aynı tokenları kullanıp farklı yapıları korur.

## DertDerman Visual Identity / Intro Animation / Motion System

Konuşma balonu biçimli D işareti ve check, bağlantı çizgisi, şirket düğümü ve çözüm noktası SVG/HTML/CSS ile üretildi. Harici icon pack, stock görsel, font veya animation library yok.

Homepage intro 780 ms sürer; tab/session içindeki ilk homepage açılışında çalışır. `sessionStorage` yalnızca `dd-brand-intro-seen` görsel tercihini saklar. Auth markası 320 ms küçük bir giriş hareketi kullanır. İçerik başlangıçtan itibaren görünür ve kullanılabilir. Sonsuz animasyon, scroll listener, history müdahalesi veya güvenlik reload'u yok. Reduced motion animasyonları ve hover translate hareketlerini kapatır.

## Homepage / Login / Register / User Experience

Ana sayfa iki alanlı hero, arama, iki CTA, özgün solution SVG, yatay metric strip, yayınlanan şikayetler ve şirket kartlarıyla yeniden kompoze edildi. Süreç bölümü masaüstünde bağlı yatay adımlar, mobilde dikey yol kullanır. Arama backend'i değiştirilmedi veya taklit edilmedi.

Auth ekranları brand story + form split layout kullanır. Mobilde tek kolon; kayıt formunda yalnızca ad/soyad yan yanadır. Sürekli görünen label, backend BoundField hata ilişkileri ve normal submit korunur.

USER paneli yeni şikayet / şikayetlerim / profil görevlerini ve gerçek son şikayetleri öne çıkarır. Profil identity + bilgi grid'i; düzenleme/şifre/complaint create ortak form shell'ini kullanır. Private complaint durum bilgileri operasyonel listelerde korunur.

## Public / Company / Custom Admin Experience

Public complaint metni 820 px panel içinde okunur. Şirket kartları logo/initial fallback ve yalnızca gerçek verification bilgisini gösterir. Company paneli aktif üyelik ve rol bağlamını görünür kılan ayrı workspace'tir. Custom admin paneli kompakt sayaç, moderasyon ve blog erişimi sunar. Publish/reject formları ve güvenlik davranışları korunur.

## Feedback Design System

Django messages üzerinden success/info/warning/error sınıfları kullanılır. Küçük bildirimler sayfa akışını itmez; çoklu uzun bildirim alanı en fazla 45vh olur ve kaydırılabilir. Her mesajda renk yanında sembol/metin vardır.

Success/info 6 saniyede kapanır; pointer/focus içindeyken zamanlayıcı durur. Error/warning kendiliğinden kapanmaz. Kapatma düğmesi yalnızca JS enhancement olarak açılır. JS kapalıysa mesajlar görünür kalır. Modal, zorunlu focus taşıma veya frontend state framework'ü yok.

## Authentication Errors

Yanlış ve var olmayan kullanıcı adı için aynı genel non-field error gösterilir: “Giriş bilgileriniz doğrulanamadı. Kullanıcı adınızı ve şifrenizi kontrol edin.” Hesabın varlığı, email veya password detayı açıklanmaz.

Ortak `field.html`, label, help text ve error ID'lerini Django'nun `aria-describedby`/`aria-invalid` davranışıyla eşleştirir. Validation backend'de kalır.

## Success States

- Profil: “Profil bilgileriniz güncellendi.”
- Şifre: “Şifreniz başarıyla güncellendi.” Django'nun session preservation davranışı korunur.
- Şikayet: “Şikayetiniz incelemeye alındı. Yayınlanmadan önce değerlendirilecektir.”
- Logout: “Oturumunuz güvenli şekilde kapatıldı.” Session kapatıldıktan sonra info mesajı oluşturulur.
- Blog: taslak kaydetme, düzenleme ve yayınlama için ayrı kısa başarı mesajları.

Mesajlar redirect sonrasında tüketilir; sonraki normal request'te aynı banner tekrarlanmaz.

## Error Pages

403 kilitli bağlantı düğümü, 404 eksik düğüm, 400/500 kesinti motifi kullanır. Hata metinleri exception, traceback, URL, token veya filesystem yolu yansıtmaz. Django'nun varsayılan 400/403/404/500 kararları korunur. CSRF için `CSRF_FAILURE_VIEW` yalnızca güvenli 403 ekranını değiştirir; korumayı bypass etmez. 405 aksiyon davranışı değişmedi.

500 template'i request veya veri tabanı içeriğine bağımlı değildir. `DEBUG=False` testlerinde gerçek test-only exception kullanıldı; uygulama DB'sine zarar verilmedi.

## Blog Model

`Post`: title, unique slug, excerpt, plain-text content, cover_image, status, created_at, updated_at, published_at. Varsayılan DRAFT; author/private admin ilişkisi bu V1'de tutulmaz. Public template'e admin bilgisi taşınmaz.

Slug bir kere güvenli title prefix + UUID ile oluşturulur ve edit'te değişmez. Aynı başlıklar çakışmaz; DB unique constraint vardır. Publication sorgusu için `(status, -published_at)` index'i eklendi. `blog/0001_initial` migration'ı oluşturuldu ve uygulandı.

## Public Blog

`/blog/` 9 kayıt/sayfa, `/blog/<slug>/` detay. Ortak selector yalnızca PUBLISHED kayıtları getirir. DRAFT slug bilinse, hatta admin public URL'ye gitse de 404 döner. `abc` ilk sayfa; negatif/sınır dışı sayfa son sayfaya düşer. Public listede content alanı yüklenmez.

Detail title ve meta description escape edilir; content CSS `white-space: pre-wrap` ile plain text olarak okunur. Raw HTML, `|safe`, rich editor veya markdown execution yok.

## Custom Admin Blog

- `/yonetim/blog/`: 12 kayıt/sayfa, status ve oluşturulma/güncelleme/yayın tarihi.
- `/yonetim/blog/yeni/`: explicit title/excerpt/content/cover_image allowlist; server DRAFT oluşturur.
- `/yonetim/blog/<pk>/duzenle/`: yalnızca allowlist alanları kaydedilir. Eşzamanlı publish state'i edit tarafından ezilmez.
- `/yonetim/blog/<pk>/yayinla/`: ADMIN + POST + CSRF, koşullu DRAFT → PUBLISHED; zamanı backend atar. Tekrar gönderim 409.

Hepsi merkezi `role_required(ADMIN)` ve private no-store davranışını kullanır. Delete/unpublish eklenmedi. Yayındaki yazıyı düzenlemek kaydedilen alanları mevcut public yazıya yansıtır; draft edit public yayınlamaz.

## Blog Image Security

Byte sınırı Pillow parse işleminden önce kontrol edilir: en fazla 5 MiB. Gerçek format JPEG/PNG/WEBP olmalıdır; filename veya browser MIME bilgisine güvenilmez. SVG/GIF, geçersiz dosya, hareketli görsel ve decompression-bomb koşulları reddedilir. Her eksen en fazla 6000 px; toplam en fazla 16 milyon piksel.

Görüntü verify/load sonrası EXIF orientation uygulanarak en fazla 1600×1600 bounding box içine küçültülür; quality 85 WebP yeniden kodlaması metadata ve trailing payload'ları kaynak dosyadan taşımadan kayıt üretir. Orijinal upload saklanmaz. Django storage, `blog/covers/<uuid>.webp` adı kullanır. Dosya yolu kullanıcı tarafından belirlenmez.

Form mevcut dosya yolunu teknik metin olarak göstermek yerine görüntüleme ve kaldırma seçeneği sunar. Eski/değiştirilmiş kapak dosyalarının otomatik storage temizliği bu V1'de uygulanmadı.

## Blog UX / Homepage Integration

Blog 3/2/1 kolon editorial grid, 16:9 cover/özgün CSS placeholder ve 800 px reading width kullanır. Cover'lar explicit dimensions, `loading="lazy"`, `decoding="async"` taşır. Uzun başlıklar ve içerikler taşmaz.

Navbar/footer ve admin workspace'e Blog bağlantıları eklendi. Homepage yalnızca son 3 PUBLISHED post'u gösterir; yazı yoksa blog bölümü gizlenir. Fake blog içeriği oluşturulmadı.

## Performance

CSS/JS tek tasarım sisteminden ve yerel dosyalardan gelir. 5 stylesheet + 1 küçük defer script yüklenir. `app.css` eski kuralları silinerek değiştirildi; üstüne yeni override yığını eklenmedi. Tek seferlik opacity/transform hareketleri, inline SVG, sabit görsel oranları kullanılır. Continuous animation/scroll listener yok.

Homepage şirket kategorileri `select_related` ile yüklenir; complaint sorgusu ilişkili şirketi zaten getirir. Homepage son 6 complaint, son 3 post ve 6 company ile sınırlıdır. Queryset pagination öncesinde Python listesine çevrilmez.

## Accessibility / Responsive

320, 360, 768, 1024 ve 1440 px genişliklerde kontrol edildi. Mobil inputlar en az 16 px; focus outline, skip link, gerçek label'lar, decorative SVG aria-hidden, status label'ları ve reduced motion bulunur. Mobil menü Escape ile kapanır ve odağı düğmeye geri verir. JS kapalı olduğunda menü bağlantıları ve formlar kullanılabilir.

Bildirimler success/info/warning için polite status, error için assertive alert kullanır. Otomatik kapanma focus'u zorla almaz. Renklerin sRGB hesaplamasında body/white 11.50:1, muted/soft-blue 5.04:1, primary-button 6.47:1, warning 5.81:1, success 5.73:1, danger 5.64:1, inverse-muted/navy 9.80:1 bulunmuştur. Bu, tüm site için bağımsız bir WCAG sertifikası değildir.

## Security Regression

Authentication/role/session kararları frontend'e taşınmadı. `/django-admin/` 404; `/yonetim/` ADMIN; `/panel/` ve private complaint alanı USER; company paneli geçerli COMPANY membership ister. Logout POST+CSRF ve session invalidation, private no-store, complaint IDOR ve publication filtreleri korunur. Yeni blog route'ları aynı modelle korunur.

Tarama: uygulama template/view kodunda `csrf_exempt`, `|safe`, `mark_safe`, `autoescape off`, kontrolsüz client status ataması, Django admin route'u veya history/pageshow security hack'i bulunmadı.

## Test Results

Tüm komutlar `conda run -n torch_gpu` ile çalıştırıldı:

| Komut | Sonuç |
| --- | --- |
| `python manage.py check` | Sorun yok |
| `python manage.py test accounts` | 35 geçti |
| `python manage.py test companies` | 14 geçti |
| `python manage.py test complaints` | 32 geçti |
| `python manage.py test adminx` | 16 geçti |
| `python manage.py test blog` | 16 geçti |
| `python manage.py test core.test_feedback` | 8 geçti |
| `python manage.py test` | 121 geçti, 46.089 saniye |
| `python manage.py makemigrations --check --dry-run` | No changes detected |

Redesign aşamasında önceki 97 test de ayrı çalıştırmada geçti; son suite bunların tamamını içerir. Blog image testleri geçerli üç format, sahte .jpg, oversized file, unsupported GIF, aşırı dimension, bomb header ve güvenli filename/storage davranışını kapsar.

## Performance Measurements

Headless Chromium: Django test client ile üretilmiş 40 ekran/durum × 5 genişlik = 200 kombinasyon. Normal, boş, error, uzun içerik, upload ve feedback durumları dahil. Snapshot'lar gerçek template/static kaynaklarını kullanır; test fixture'ları yalnızca ayrı test DB'sindedir.

| Ölçüm | Sonuç |
| --- | --- |
| Yatay overflow | 0 |
| Static/media asset hata cevabı | 0 |
| Harici network isteği | 0 |
| Duplicate CSS/JS yükleme | 0 |
| JS error | 0 |
| Eksik label / aria-describedby hedefi | 0 |
| Mobil input <16 px | 0 |
| Homepage sorgusu | 5; artan kayıt sayısında sabit |
| Blog list sorgusu | 2; artan kayıt sayısında sabit |
| Toplam CSS | 31,299 byte, sıkıştırılmamış kaynak |
| UI JavaScript | 2,312 byte, sıkıştırılmamış kaynak |
| Intro once / reduced motion / no-JS / storage blocked | Geçti |
| Notification timeout / keyboard-focus pause | Geçti |
| LCP / CLS / INP / Lighthouse | NOT MEASURED |

Bu ölçümler production ağ gecikmesi veya düşük güçlü gerçek cihaz performansı garantisi değildir. QA scriptleri, test kapakları, JSON ve PNG çıktıları geçicidir; repo kaynak dosyası olarak eklenmedi.

## Files Changed

Aşağıdaki liste redesign ve onu takip eden UX/blog çalışmasını kapsar. Önceki route hardening/moderation görevlerinin değişmeden kalan dosyaları bu listeye dahil değildir. Yollar `dertderman/` altındadır.

### Backend, tests ve migration

- `accounts/views.py`
- `adminx/urls.py`
- `adminx/blog_views.py`
- `blog/models.py`
- `blog/forms.py`
- `blog/selectors.py`
- `blog/views.py`
- `blog/urls.py`
- `blog/tests.py`
- `blog/migrations/0001_initial.py`
- `blog/templates/blog/cover_widget.html`
- `complaints/views.py` (yalnızca başarı mesajı metni)
- `config/settings.py` (CSRF failure ekranı)
- `config/urls.py` (blog include)
- `core/views.py` (homepage blog ve kategori sorgusu)
- `core/error_views.py`
- `core/test_feedback.py`

### Static

- `static/css/app.css` kaldırıldı
- `static/css/tokens.css`
- `static/css/base.css`
- `static/css/components.css`
- `static/css/pages.css`
- `static/css/motion.css`
- `static/js/ui-motion.js`

### Layout / errors / components

- `templates/base.html`
- `templates/home.html`
- `templates/400.html`
- `templates/403.html`
- `templates/404.html`
- `templates/500.html`
- `templates/csrf_failure.html`
- `templates/components/auth_story.html`
- `templates/components/brand.html`
- `templates/components/company_card.html`
- `templates/components/company_identity.html`
- `templates/components/error_visual.html`
- `templates/components/feedback.html`
- `templates/components/field.html`
- `templates/components/icon.html`
- `templates/components/pagination.html`
- `templates/components/solution_visual.html`
- `templates/components/workspace_nav.html`

### Product templates

- `templates/accounts/login.html`
- `templates/accounts/register.html`
- `templates/accounts/profile.html`
- `templates/accounts/profile_edit.html`
- `templates/accounts/password_change.html`
- `templates/dashboard/home.html`
- `templates/companies/company_list.html`
- `templates/companies/company_detail.html`
- `templates/companies/company_dashboard.html`
- `templates/companies/company_panel_detail.html`
- `templates/complaints/complaint_create.html`
- `templates/complaints/complaint_list.html`
- `templates/complaints/complaint_detail.html`
- `templates/complaints/public_list.html`
- `templates/complaints/public_detail.html`
- `templates/complaints/public_card.html`
- `templates/adminx/home.html`
- `templates/adminx/complaint_list.html`
- `templates/adminx/complaint_detail.html`
- `templates/adminx/blog_list.html`
- `templates/adminx/blog_form.html`
- `templates/blog/post_list.html`
- `templates/blog/post_detail.html`
- `templates/blog/card.html`
- `templates/blog/status_badge.html`
- `UI_UX_V2_REPORT.md`

## Status

**IMPLEMENTED:** Redesign V2, ortak feedback/error sistemi, public blog, custom admin create/edit/publish ve image normalization.

**TESTED:** 121 Django testi; 200 headless ekran/genişlik kombinasyonu; bounded queries, local assets, notification/focus/reduced-motion/no-JS.

**NOT YET IMPLEMENTED:** Blog delete/unpublish, rich editor, otomatik eski kapak temizliği, audit/security logging, persistent notification inbox, gerçek backend arama. Bu görevde istenmeyen payment/comments/response özellikleri eklenmedi.

**PRODUCTION HARDENING REQUIRED:** DEBUG=False, secret/host/origin yönetimi, HTTPS/secure cookies/HSTS, trusted proxy, rate limiting, güvenli media sunumu ve request-body sınırları, audit/security logging; gerçek cihaz/production performans ölçümü. Local HTTP çalışma koşulları korunur.
