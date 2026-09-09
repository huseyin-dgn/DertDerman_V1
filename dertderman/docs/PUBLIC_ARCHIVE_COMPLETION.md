# Public şirketler, blog okuyucu ve admin arşivleme doğrulaması

8 Eylül 2026. Önceki uncommitted çalışma korundu; özellikler baştan yazılmadı.

Başlangıçta 49 takip edilen dosyada değişiklik, ayrıca yeni kaynaklar, migrationlar ve önceki admin QA çıktıları vardı. `git status`, `git diff --stat`, bütün takip edilen diff ve yeni kaynak dosyalar incelendi. Büyük `base.html` değişikliğinin silinmiş içerik olmadığı; public/company layout dosyalarına taşınmış içerik olduğu karşılaştırıldı. Eski QA raporu bu turun sonucu olarak kullanılmadı. [Dosya bazlı inceleme](PUBLIC_ARCHIVE_FILE_REVIEW.md) her dosyanın amacını listeler.

## Tamamlanan eksikler

- Şirket erişim helper'ı yalnızca `is_active` üzerinden arşivlemeye güveniyordu. `companies/services.py` artık `archived_at IS NULL` koşulunu da uygular.
- Şirket giriş formu ayrı bir üyelik sorgusu kullanıyordu. `companies/forms.py` ortak helper'a bağlandı; login/panel politikası aynı. Arşivli şirketin aktif bayrağı sonradan açılsa bile giriş ve panel kapalı kalır.
- `adminx/views.py` içindeki aktivite listesi 10 kayıt kullanıyordu; bütün admin listeleri için istenen 5 kayıt standardına getirildi. `adminx/test_v2.py` buna uyarlandı.
- `static/css/discovery.css` mobil okuyucuyu kenar boşluklu pencereden gerçek tam ekrana geçirir.
- `static/js/article-reader.js` Tab/Shift+Tab odak döngüsünü tamamlar; liste kaydırma konumu gövde sabitlenmeden önce tarayıcı geçmişine kaydedilir.
- `blog/tests.py` içindeki eski düz metin beklentisi yeni paragraf/`br` çıktısına uyarlandı. Script/HTML kaçış kontrolü korunur.
- `adminx/test_archiving.py` arşiv markerının tek başına erişimi engellemesini ve eski bir düzenleme nesnesinin arşivlemeyi geri alamamasını test eder. Mevcut içerik düzenleme allowlist'leri zaten arşiv alanlarını koruyordu; bunlar yeniden yazılmadı.
- `scripts/qa_public_archive.py` bu hedefleri geçici veritabanı ve gerçek Edge tarayıcısıyla tekrar doğrulayan QA scriptidir.

## Migration

Mevcut migrationlar eksiksiz ve model choices ile uyumlu bulundu; yeni migration üretmek gerekmedi.

| Migration | Sonuç |
|---|---|
| `blog/0002_post_author.py` | Önceden uygulanmış; sıfırdan test DB kurulumu da başarılı. |
| `blog/0003_alter_post_status.py` | Bu tur yerel DB'ye başarıyla uygulandı. ARCHIVED, mevcut 12 karakterlik alana uygundur. |
| `companies/0004_company_archived_at.py` | Bu tur yerel DB'ye başarıyla uygulandı. |

Önce SQLite backup alındı: `C:/Users/hdgn5/AppData/Local/Temp/dertderman-before-archive-migration-6673xwdw/db.sqlite3`.
Migration sonrasında mevcut kolonlar ve bütün satırlar yedekle karşılaştırıldı: 2 blog, 7 şirket, 2 üyelik, 1 şirket cevabı, 3 şikayet aynı kaldı; dahili not tablosunda zaten 0 kayıt vardı. Dahili not koruması ayrıca dolu test fixture'ıyla doğrulandı.

`makemigrations --check --dry-run`: değişiklik yok. `migrate --check`: bekleyen migration yok. `manage.py check`: sorun yok.

## Arşiv davranışları ve güvenlik

Blogdaki **Sil** işlemi fiziksel silme yapmaz; `status=ARCHIVED` yazar. İçerik, yazar ve kapak ilişkisi korunur. Ana sayfa, public liste, direct detail ve reader fragment erişiminden çıkar. Direct/fragment istekleri 404 alır. Varsayılan admin blog listesinde gizlenir; ARCHIVED filtresiyle görülebilir. Eski düzenleme/yayınlama endpointleri arşivli yazıyı yeniden açamaz.

Şirket arşivleme `is_active=False` ve `archived_at` yazar; mevcut onay durumu ve ilişkili kayıtlar korunur. Complaint, CompanyMembership, CompanyResponse, InternalCompanyNote ve mevcut bildirimler silinmez. Bir arşiv bildirimi oluşturulur. Public liste/ana sayfa/detay görünürlüğü kapanır. Açık şirket oturumları sonraki istekte yeniden denetlenerek engellenir; login de aynı politikayı uygular. Hesabın başka erişilebilir şirket üyeliği varsa o üyelik korunur. Arşivli pending başvuru yeniden onaylanamaz.

İki işlem de ADMIN rolüne, POST'a ve CSRF'ye bağlıdır. USER ve COMPANY 403 alır; staff/superuser bayrağı tek başına ADMIN rolünü aşamaz. Anonim kullanıcı girişe yönlenir. GET/HEAD/PUT/DELETE durum değiştirmez. Eksik CSRF 403; geçerli CSRF ile ADMIN başarılıdır. Tekrarlanan arşivleme idempotent, olmayan kayıt 404'tür. Confirmation iptali kayıt değiştirmez; onay, orijinal POST formunu gönderir.

## Public listeler ve okuyucu

| Liste | Kayıt/sayfa | Sıralama |
|---|---:|---|
| Public şirketler | 8 | `-created_at, -pk` |
| Public blog | 6 | `-published_at, -pk` |
| Admin listeleri, aktivite dahil | 5 | `-created_at, -pk`; kullanıcılar `-date_joined, -pk` |

Public şirketler yalnızca APPROVED + active + arşivlenmemiş kayıtları gösterir. Doğrulanma rozeti public görünürlüğün ek önkoşulu değildir. Blog yalnızca PUBLISHED gösterir. Filtreleme sayfalamadan önce yapılır. Sayfa 2, son sayfa, kesin sıralama, tekrar/atlama olmaması, boş sonuç, geçersiz sayfa ve arama/filtre querystring koruması doğrulandı.

Reader kart görseli/başlık/Oku bağlantılarıyla açılır; içerik mevcut detail URL'den fragment olarak yüklenir. Listeye bütün yazı gövdeleri gömülmez. ESC, backdrop, kapatma, Tab/Shift+Tab, odağın karta dönüşü, body scroll lock/restore, tarayıcı geri/ileri davranışları test edildi. Ağ hatasında ayrı sayfa bağlantısı sunulur. JS kapalıyken normal anchor direct detail sayfasına gider. Ortak article şablonu Django autoescaping kullanır. Ağır JS kütüphanesi eklenmedi.

## Responsive ve browser QA

Uygulama içi Browser bağlantısı kullanılamadığı için yerel Playwright / Microsoft Edge 152.0.4191.66 kullanıldı. QA kayıtları geçici DB'dedir; proje DB'sine demo kayıt eklenmedi.

| Viewport | Şirket sütunu | Blog sütunu | Modal ve iki confirmation | Sayfa taşması |
|---|---:|---:|---|---|
| 375 × 812 | 1 | 1 | Başarılı, reader tam ekran | Yok |
| 430 × 932 | 1 | 1 | Başarılı, reader tam ekran | Yok |
| 768 × 1024 | 2 | 2 | Başarılı | Yok |
| 1024 × 768 | 2 | 2 | Başarılı | Yok |
| 1366 × 768 | 4 | 3 | Başarılı | Yok |
| 1440 × 900 | 4 | 3 | Başarılı | Yok |

Her boyutta public kart sayıları, iki listenin sayfa 2'si, modal ve admin blog/company onay açma/iptal/odak kontrol edildi. Admin tabloları kendi kapsayıcısında yatay kayar. Örnek mobil/tablet/desktop ekran görüntüleri ayrıca görsel olarak incelendi. Gerçek arşiv POST'ları ve arşiv filtreleri fixture kayıtlarıyla doğrulandı. JavaScript hatası: 0.

Kanıtlar: [QA JSON](public-archive-qa/results.json), [desktop şirketler](public-archive-qa/directory-1440.png), [desktop blog](public-archive-qa/journal-1440.png), [mobil reader](public-archive-qa/reader-375.png), [mobil şirket onayı](public-archive-qa/company-confirm-375.png), [mobil blog onayı](public-archive-qa/blog-confirm-430.png). Diğer viewport PNG'leri aynı dizindedir. Bu doğrulama Edge üzerinde yapılmıştır; Safari/Firefox veya fiziksel telefon testi yapıldığı iddia edilmez.

## Test sonucu

- Önce ilgili paketler: **117 test başarılı** (16,877 saniye).
- Ardından full suite: **229 test başarılı** (46,926 saniye). [Test çıktısı](full-suite-current.txt).
- JS dosyaları `node --check`, ilgili Python paketleri compile kontrolü ve `git diff --check` başarılı.
- Browser QA'nın başarılı kontrolleri `public-archive-qa/results.json` içinde; tekrar çalıştırma: `python scripts/qa_public_archive.py`.

Değişiklikler çalışma ağacında bırakıldı; commit veya deploy yapılmadı.

Son başarılı QA koşusu geçici verilerini temizleyerek exit 0 ile tamamlandı. Önceki başarısız QA koşusundan kalan `C:/Users/hdgn5/AppData/Local/Temp/dertderman-public-qa-w8mr64pm` klasörünü sonradan silme komutu otomatik güvenlik denetiminde “blocked by policy” gerekçesiyle reddedildi; bu eski test klasörü yerinde bırakıldı.
