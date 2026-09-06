# DertDerman — motion ve platform arayüzü

Mevcut redesign korunarak tamamlanan özellikler:

- Login ve register ortak auth alanında özgün inline SVG: düğümlenmiş dert, iletişim balonları, süreç belgesi ve çözüm işareti. Çizgi bir kez 1000 ms'de çizilir. İki küçük CSS noktası SVG eğrisinden örneklenen konumları 14 saniyede takip eder. Hareket transform/opacity ile uygulanır; asset veya template indirilmedi.
- Mouse-follow iki auth ekranında da korunur: üç katman, farklı derinlik, eksen başına en fazla 8 SVG birimi; pointer ayrılınca yumuşak dönüş. RAF yerleşince durur, ölçüm pointer girişinde yapılır.
- Brand strip 48 saniyelik yatay CSS döngüsü kullanır. Tek erişilebilir metin, ekran okuyuculardan gizlenen iki görsel kopya vardır. Hareketi durdur/sürdür kontrolü bulunur; kontrol için yer ayrılarak JS'nin geç yüklenmesinde yeni layout kayması önlenir.
- IntersectionObserver görünmeyen hareket alanlarını durdurur. Gizli sekmede motion ve RAF durdurulur. Mobilde auth görseli gizlenir, şerit statiktir. Reduced-motion altında animasyonlar kapalıdır. JS olmadan formlar ve gerçek metrik değerleri kullanılabilir.
- Ana sayfanın merkez container'ı 1248 px, navbar 68 px; footer lacivert ve daha belirgin içerik hiyerarşisine sahip. Complaint kartları, şirket dizini ve editorial blog yerleşimi korunur. Motifler auth hikayesi, çözüm yolu ve süreç göstergeleriyle sınırlıdır.
- Metrik alanında gerçek toplam şikayet, kayıtlı şirket, kullanıcı, yayınlanan şikayet ve çözülen şikayet sayıları vardır. 700 ms count-up tek sefer çalışır. Asıl sunucu değeri erişilebilir DOM'da ve yerleşimde kalır; geçici animasyon katmanı ayrı ve aria-hidden'dır.
- Private complaint detail içinde yatay/telefonlarda dikey lifecycle: doğrulanabilen gönderim ve güncel durum. Bekleyen sonuç nötr, gönderim/çözülmüş durum yeşil, reddedilmiş durum kırmızı. Kaydedilmeyen geçmiş aşamalar tamamlanmış gösterilmez. Şirket yanıtı gibi desteklenmeyen statüler üretilmez.
- Ana sayfa çözüm yolu dört gerçek ürün adımını anlatır; 1000 ms çizim ilk görünürlükte bir defa çalışır. Mobilde dikey statik çizgi kullanılır. Yayın veya çözüm garantisi verilmez.
- Şirket detayında en fazla son beş halen public şikayet listelenir. Başlık “Yayındaki şikayet”, tarih etiketi “Oluşturulma”dır. created_at yayın/çözüm tarihi olarak sunulmaz. updated_at olay tarihi olarak kullanılmaz. Veri yoksa sade empty-state vardır.

## Veri ve güvenlik

Fake trend, rakam, kullanıcı, tarih, activity veya state eklenmedi. Production verisine test kaydı yazılmadı. Sayısal toplamlar veritabanından hesaplanır, boş toplamlar sıfırdır. Tarihsel veri olmadığı için trend oku/yüzdesi yoktur.

Toplam ve çözülen şikayet sayıları aggregate bilgidir; özel kayıtların metinleri aktarılmaz. Yayınlanan sayı aktif şirketlere ait PUBLISHED kayıtları sayar. Mevcut `public_complaints()` değiştirilmedi: RESOLVED public görünürlük sağlamaz; inactive şirket kayıtları dışarıda kalır. Activity aynı selector'ı kullanır.

Auth, role, IDOR, session, CSRF, logout, private no-store kodu değiştirilmedi. Backend değişiklikleri public ana sayfa metrik context'i ve public şirket detail activity context'iyle sınırlıdır. Şema değişikliği yoktur.

## Doğrulama

- `python manage.py check`: temiz.
- `python manage.py makemigrations --check --dry-run`: No changes detected.
- `python manage.py test`: 130 testin tamamı geçti (önceki 127 test + 3 demo komut testi); role/session/IDOR/CSRF/no-store ve `/django-admin/` → 404 kontrolleri dahil.
- Catch-all kullanıcı tarafından bilinçli olarak istenen davranıştır ve korundu. Test beklentisi buna göre güncellendi: DEBUG=True ve DEBUG=False altında `/312`, `/olmayan-bir-url/`, `/django-admin/` → HTTP 404 + custom `404.html`. Gerçek `/`, `/hesap/giris/`, `/blog/`, `/sikayetler/` route'ları normal çalışır; `/panel/` anonim kullanıcıyı girişe yönlendirir, USER için 200 + no-store döndürür. Geçici gerçek media dosyası DEBUG=True altında `django.views.static.serve` tarafından 200 ile sunuldu; catch-all intercept etmedi. DEBUG=False custom 400/403/404/500/CSRF render kontrolleri de geçti.
- Yeni backend testleri: gerçek/boş metrik toplamları, özel veri gizliliği, public selector korunması, activity sıralama/limit/tarih anlamı ve dört lifecycle statüsü.
- Ana sayfa 6 sabit sorgu, blog listesi 2. Yeni aggregate sorgusu nedeniyle mevcut performans testi 5 yerine 6 sınırına güncellendi; artan kayıt sayısıyla N+1 kontrolü korunur. Şirket activity detail 2 sorgu, beş kayıtla sabit; testte doğrulandı.
- Headless Chromium: 44 ekran/durum × 320, 360, 768, 1024, 1440 px = 220 kontrol. Yatay taşma, JS hatası, static/media 404, dış istek, yinelenen asset, eksik form label/description referansı yok.
- Klavye ile şifre göster/gizle ve mobil menü, JS kapalı, storage kullanılamaz, reduced-motion, touch cihaz, pointer derinlik/dönüş/idle, kullanıcı motion pause, görünmez alan/gizli sekme, count-up final değeri, çözüm yolu tek seferlik çizim ve bildirim davranışları doğrulandı.
- Count-up CLS: 0. Yerel Chromium sürekli auth animasyon örneği: 1,2 saniyede yaklaşık 35 ms ana iş parçacığı zamanı, 0 layout. JS toplam 8,3 KB; dış kütüphane, font/CDN isteği, GIF/video, scroll listener yok.
- JS yüklemesi 800 ms geciktirilen auth kontrolünde CLS: 0. Son ek ölçümde 1,2 saniyelik hareket 26 ms / 0 layout; kullanıcı duraklatmasında 2 ms / 0 layout.
- QA çıktıları: `C:/Users/hdgn5/AppData/Local/Temp/dd-ui-motion-qa/` (report.json ve ekran görüntüleri). Test veritabanı ve media geçici alandadır.

## Bu görevde değiştirilen dosyalar

- `core/views.py`
- `companies/views.py`
- `core/test_platform_ui.py` (yeni)
- `blog/tests.py`
- `static/css/base.css`
- `static/css/components.css`
- `static/css/pages.css`
- `static/css/motion.css`
- `static/js/ui-motion.js`
- `templates/base.html`
- `templates/home.html`
- `templates/components/auth_story.html`
- `templates/components/auth_visual.html` (yeni)
- `templates/components/brand_strip.html` (yeni)
- `templates/components/metric.html` (yeni)
- `templates/components/solution_path.html` (yeni)
- `templates/complaints/complaint_detail.html`
- `templates/complaints/lifecycle.html` (yeni)
- `templates/companies/company_detail.html`
- `MOTION_UI_REPORT.md` (yeni)

Görsel kimlik değerlendirmesi: Logo dışında auth'taki düğümden çözüm işaretine geçiş, ana sayfanın çözüm yolu, private süreç çizgisi ve tarihleri doğru etiketlenmiş activity listesi DertDerman'a özgü akışı taşıyor. Aynı dekoratif SVG her bölüme eklenmedi.

## Development/test demo şirketleri

Kullanıcının açık isteğiyle `python manage.py seed_demo_companies` eklendi ve yerel DEBUG=True veritabanında çalıştırıldı. Oluşturulan beş aktif şirket:

- Demo Teknoloji
- Demo Market
- Demo Kargo
- Demo Telekom
- Demo Banka

İsim ve açıklamalar demo/test amacını açıkça belirtir. Komut `get_or_create` kullanır; tekrar çalıştırıldığında sıfır yeni kayıt oluşturduğu doğrulandı. Daha önce pasife alınmış demo kaydı tekrar aktif hale getirilir; diğer şirketler değiştirilmez. DEBUG=False altında komut veritabanına erişmeden CommandError ile reddedilir. Otomatik migration, startup seed veya production seed akışına bağlanmadı.

Mevcut USER hesabıyla render edilen `/sikayet-olustur/` formunun select alanında beş şirketin tamamı doğrulandı; public şirket listesinde de görünürler. Komut kullanıcı, membership veya şikayet oluşturmaz; tekrar çalıştırma öncesi/sonrası bu tabloların sayıları değişmedi. Company modeli, publication selector ve güvenlik kuralları korunur.

Bu takip işinde güncellenen/eklenen dosyalar: `core/test_feedback.py`, `companies/management/__init__.py`, `companies/management/commands/__init__.py`, `companies/management/commands/seed_demo_companies.py`, `companies/test_demo_command.py`, bu rapor. URL yapılandırması değiştirilmedi.
