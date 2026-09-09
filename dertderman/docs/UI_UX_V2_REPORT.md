# DertDerman UI/UX — Admin V2 ve listeleme standardı

Tarih: 8 Eylül 2026

İlk aşama tamamlandı. `/yonetim/` bağımsız bir operasyon ekranına taşındı; mevcut rol kontrolü, oturum sistemi, şirket onayı ve moderasyon servisleri korundu. Değişiklikler çalışma ağacındadır; commit veya dağıtım yapılmadı.

## 1. İnceleme ve kapsam

`base.html`, workspace navigasyonu, adminx route/view/decorator yapıları, dashboard, accounts, companies, complaints, blog, notifications, CSS token/component dosyaları ve bütün çalışan liste ekranları incelendi. Başlangıçta 191 test başarılıydı.

Admin şikayet/başvuru listeleri, kullanıcı şikayetleri, public şirket dizini ve şirket yetkili listesi sınırsızdı. Diğer listelerde 9/12/15/20 gibi farklı limitler ve üç ayrı pagination HTML'i vardı. Şirket şikayet detayındaki hareket geçmişi eski olayları erişilemez kılan sabit kesitlerden oluşturuluyordu.

## 2. Rol layout mimarisi

| Rol | Layout | Uygulama |
|---|---|---|
| PUBLIC | `templates/layouts/public_base.html` | Mevcut public navbar, footer ve görsel yapı taşındı. `base.html` uyumluluk girişidir. |
| USER | `templates/layouts/user_base.html` | Kişisel alana ait kısa header; mevcut panel, profil ve form içerikleri korundu. Public keşif navbar'ı kullanılmaz. |
| COMPANY | `templates/layouts/company_base.html` | Çalışan şirket sidebar/header aynen taşındı; eski panel base'i uyumluluk girişidir. |
| ADMIN | `templates/layouts/admin_base.html` | Ayrı sidebar, header, içerik alanı, breadcrumb, feedback ve onay penceresi. |

Kullanıcı panelinin kapsamlı tasarımı, login/register ekranları, intro, homepage hero/carousel/metrics, public şirket kartlarının tasarımı ve blog modal okuyucusu bu aşamada yeniden tasarlanmadı. Public detaylarda sadece ortak pagination bağlantısı değişti. Marka, ikon ve mevcut buton/alan bileşenleri yeniden kullanıldı.

## 3. Admin sidebar ve header

Genel Bakış, Şikayetler, Şirketler, Şirket Başvuruları, Kullanıcılar, Blog, Bildirimler, Sistem / Aktivite ve Site İçerikleri bağlantıları çalışır. Mevcut ayar düzenleme route'u olmadığı için sahte bir Ayarlar ekranı oluşturulmadı; mevcut ana sayfa içerik ekranı Site İçerikleri olarak bağlandı.

Aktif bölüm detay ekranlarında da işaretlenir. Header bölüm adını, bildirim kısayolunu, yeni yazı aksiyonunu ve POST/CSRF çıkışını içerir. Yönetici kimliği sidebar'dadır. Desktop'ta sticky sidebar, tablette dar sidebar, mobilde drawer kullanılır. Drawer Escape ve arka plan tıklamasıyla kapanır; odak geri döner ve klavye odağı menü içinde tutulur. JavaScript yokken navigasyon açık kalır.

## 4. Dashboard KPI'ları

Sekiz kart doğrudan veritabanından hesaplanır: toplam hesap, toplam şirket, bekleyen şirket başvurusu, bekleyen şikayet, yayındaki şikayet, çözülen şikayet, yayındaki blog ve son 7 günde kaydedilen şirket olayları. Durum kartları ilgili filtreli listeye gider. Trend uydurulmadı.

Son şikayetler, bekleyen başvurular, son kullanıcılar ve son blog yayınları ayrı önizleme alanlarıdır; her biri en fazla 5 kayıt ve Tümünü Gör bağlantısı içerir. Dashboard'da pagination bulunmaz.

## 5. Admin tabloları ve detaylar

- Şikayetler: ID, başlık, kullanıcı adı, şirket, tarih, durum, İncele.
- Şirket başvuruları: şirket, kategori, ilk bağlı başvuran hesabı, kurumsal e-posta, tarih, durum, İncele. Mevcut sistemde ayrı başvuru modeli olmadığından Company kayıtları kullanılmaya devam eder.
- Şirketler: logo veya harf simgesi, isim, kategori, doğrulama, aktiflik, onay, şikayet sayısı, Düzenle.
- Kullanıcılar: isim, e-posta, kayıt tarihi, rol, aktiflik ve yeni salt okunur detay bağlantısı. Parola/hash/session bilgileri gösterilmez.
- Blog: başlık, durum, yazar, oluşturma/yayın tarihleri ve Düzenle. Yeni yazı oluşturma ve yayınlama akışları korunur.
- Bildirimler/aktivite: mevcut CompanyNotification kayıtlarının olay, şirket, tür, tarih ve ilgili kayda erişim bilgileri.

Tablolar ortak `adminx/table_base.html` kullanır. Yatay taşma tablo alanında kalır; dar ekranlarda kaydırma açıklaması bulunur. Detay ve düzenleme sayfaları breadcrumb içerir.

## 6. Arama ve filtreler

`adminx/filters.py` form doğrulaması, arama, sıralama ve sayfalama bağlamını ortaklaştırır.

| Liste | Filtreler |
|---|---|
| Şikayet | Başlık/kullanıcı/şirket araması, durum, şirket |
| Şirket | İsim/e-posta araması, kategori, doğrulama, aktiflik, onay |
| Başvuru | Şirket/e-posta/başvuran araması, PENDING/APPROVED/REJECTED |
| Kullanıcı | İsim/kullanıcı adı/e-posta araması, rol, aktiflik |
| Blog | Başlık/özet araması, durum |
| Bildirim/aktivite | Başlık/şirket araması, olay türü, son 7 gün |

`q` ve mevcut örneklerle uyumluluk için `s` desteklenir. Şikayet listesi ilk açılışta mevcut moderasyon kuyruğunu koruyarak PENDING gösterir; `?status=` bütün durumları açar. Geçersiz filtreler doğrulama mesajı ve boş sonuç üretir. Formdaki şirket/kategori seçenekleri seçim kontrolleridir; kayıt tablolarından bağımsızdır.

## 7. Ortak pagination

`core/pagination.py` sunucu tarafında Django Paginator kullanır. `components/pagination.html` ve `pagination_tags.py` numaralı, gerektiğinde elided sayfalar, aktif durum, önceki/sonraki pasif durumları ve kayıt aralığı sağlar. Eski pagination partial'ları ortak bileşene yönlenir.

Querystring güvenli biçimde kopyalanır; yalnızca ilgili sayfa parametresi değiştirilir. Aramalar, filtreler, tekrarlanan parametreler ve detay sayfalarındaki `response_page`, `note_page`, `history_page` birbirini silmez. `abc` ilk sayfaya; negatif/sınır dışı değerler Paginator'ın güvenli son sayfasına gider. Boş listelerde de 500 oluşmaz.

## 8. Sayfa boyutları ve liste envanteri

| Alan | Sayfa başına |
|---|---:|
| Admin şikayetler | 5 |
| Admin şirket başvuruları | 5 |
| Admin şirketler | 5 |
| Admin kullanıcılar | 5 |
| Admin blog | 5 |
| Admin bildirimler | 5 |
| Admin başvuru detayındaki yetkililer | 5 |
| Public şirketler | 8 |
| Public şikayetler | 8 |
| Public blog | 6 |
| Kullanıcı şikayetleri | 6 |
| Şirket şikayetleri | 6 |
| Şirket cevap listesi ve detay cevapları | 6 |
| Public şikayet detayındaki şirket cevapları | 6 |
| Şirket bildirimleri | 8 |
| Şirket yetkilileri | 6 |
| Şirket dahili notları | 10 |
| Şirket şikayet hareket geçmişi | 10 |
| Admin aktivite | 10 |
| Admin dashboard: her önizleme | en fazla 5 |
| Şirket dashboard önizlemesi | en fazla 5 |
| Kullanıcı dashboard önizlemesi | mevcut 3 |
| Public şirket detay önizlemesi | mevcut 5 |

Public homepage, korunması istenen mevcut 6 şirket / 6 şikayet / 3 blog kesitini korur; bunlar sınırsız listeler değildir. Kategori seçenekleri ve yetkili olunan şirketi değiştirme kontrolü kayıt listesi değildir; erişim seçimi davranışı korunmuştur.

`notifications` uygulamasında kullanıcı bildirimi modeli/view/route bulunmadığı doğrulandı. Çalışmayan bir bildirim ekranı yaratılmadı; gelecekteki kullanıcı bildirimi için ortak limit 8 olarak tanımlandı. Ayrı bir genel audit modeli bulunmuyor. Admin aktivite ekranı yalnızca mevcut şirket olaylarını temsil eder; tam güvenlik audit geçmişi olduğu iddia edilmez.

## 9. Sıralama ve sorgular

Listeler `-created_at, -pk`; kullanıcılar `-date_joined, -pk`; public/yayındaki blog önizlemeleri `-published_at, -pk` sıralıdır. Eşit tarihlerde PK ile deterministik sıralama korunur. Filtreleme pagination'dan önce uygulanır. Şikayet sayıları aggregate, başvuran kişi tek satırlık subquery ile alınır.

Şirket hareket geçmişi artık SQL UNION ve Paginator kullanır. Yanıt/not/olaylar belleğe sınırsız yüklenmez ve eski hareketler kesilmez. Şirket kapsamı sorgularda korunur. Tarih eşitliğinde kaynak ve olay ID'si sıralamayı kararlı tutar.

## 10. Empty state ve metinler

Ortak ikon, başlık, açıklama ve CTA içeren empty state oluşturuldu. Liste filtrelerinin boş sonuçları ve veri bulunmaması ele alındı. Admin içerik ekranındaki geçici sürüm/geliştirme anlatımı kaldırıldı. Gerçek ürüne demo kayıt eklenmedi. Tarayıcı QA verileri yalnızca geçici bir veritabanında oluşturuldu ve temizlendi.

## 11. Feedback ve kritik aksiyonlar

Mevcut Django messages bileşeni başarı/hata/uyarı görünümleri ve kapatma düğmesiyle kullanılır. Browser alert/confirm yoktur. Şikayet ve şirket başvurusu ret düğmeleri erişilebilir native dialog ile onay ister; vazgeçmek POST göndermez. Onayda orijinal form, CSRF token'ı ve submitter action değeri korunur. Backend durum geçişleri değiştirilmedi. JS kapalıysa mevcut POST davranışı sürer; modal ek bir istemci UX katmanıdır.

## 12. Güvenlik ve migration

| Senaryo | Sonuç |
|---|---|
| USER → `/yonetim/` ve yönetim alt ekranları | 403, erişemez |
| COMPANY → `/yonetim/` ve yönetim alt ekranları | 403, erişemez |
| ADMIN → `/yonetim/` ve yönetim alt ekranları | 200, başarılı |
| Anonim → yönetim | Custom admin girişine yönlendirme |
| `/admin/`, `/django-admin/` | 404 |
| Durum değiştiren işlem GET | Mevcut method kısıtları korunur |
| Eksik CSRF ile kritik POST | 403 |

`admin_required`, `role_required`, custom admin login, accounts.User parola sistemi, Django auth/session, CompanyMembership ve şirket login/onay servisleri değiştirilmedi. Yeni okuma route'larında aynı ADMIN enforcement, require_safe ve no-store davranışı kullanılır. Kullanıcı detayları izin verilen alanlarla sorgulanır. Şirket cevap/not tenant izolasyonu ve hassas veri/XSS testleri başarılıdır.

Blog modeline nullable `author` ForeignKey eklendi (`blog/0002_post_author`). Yazar yeni yazıda request.user'dan atanır; istemci farklı yazar gönderemez. Düzenleme/yayınlama yazarı değiştirmez. Eski kayıtlar Belirtilmemiş gösterir. Migration yerel veritabanına uygulandı; bekleyen migration yoktur. Başka ortama aktarırken standart `python manage.py migrate` gerekir.

## 13. Responsive QA

Yerel Playwright / Microsoft Edge 152 ile 14 admin route'u aşağıdaki boyutlarda doğrulandı: 1440×900, 1366×768, 1024×768, 768×1024, 430×932 ve 375×812. Toplam 84 sayfa/boyut kontrolünde belge genelinde yatay taşma yok; tablolar kendi alanlarında kayar. Aktif menü, mobil drawer, Escape, odak dönüşü, arama/filtre/sayfa 2, iki farklı ret formu, başarı mesajı ve boş sonuç kontrolleri geçti. JavaScript hatası yok.

Uygulama içi Browser bağlantısı kullanılamadığı için yerel Playwright kullanıldı. Son ekran görüntüleri desktop/tablet/mobile, drawer ve confirmation bakımından görsel olarak incelendi.

- [Desktop dashboard](admin-v2-qa/dashboard-1440.png)
- [Şirket başvuruları](admin-v2-qa/sirket-basvurulari-1440.png)
- [Mobil şikayet listesi](admin-v2-qa/sikayetler-375.png)
- [Mobil menü](admin-v2-qa/drawer-375.png)
- [Ret onayı](admin-v2-qa/confirmation-1440.png)
- [Makine tarafından okunabilir QA sonucu](admin-v2-qa/results.json)

Tekrar çalıştırma: `python scripts/qa_admin_v2.py`. Script Playwright ve Edge gerektirir; normal Django test paketinin bağımlılığı değildir. Görsellerdeki kayıtlar test fixture'larıdır.

## 14. Test sonuçları ve değişen dosyalar

- Başlangıç: 191 test başarılı.
- Son durum: **207 test başarılı**, 43,745 saniye, hata/başarısızlık yok.
- Yeni testler: `adminx/test_v2.py` (10), `core/test_pagination.py` (6).
- Mevcut sayfa boyutu ve KPI metin testleri yeni gereksinime uyarlandı; güvenlik/iş akışı testleri kaldırılmadı.
- Admin sayfa 2, kararlı newest-first, tekrar/atlama olmaması, invalid page, filtre/querystring, preview limitleri, erişim ve yazar ataması doğrulandı.
- Şirket approve/reject, complaint publish/reject, blog create/edit/publish, CSRF, logout ve tenant isolation mevcut tam paketle doğrulandı.
- `manage.py check`, `makemigrations --check --dry-run`, `migrate --check` başarılı.

[Tam test çıktısı](admin-v2-qa/test-results.txt) ve [değişen dosya envanteri](admin-v2-files.txt) rapora dahildir.

Ana değişiklik grupları: adminx view/filter/context/route dosyaları; dört layout ve admin şablonları; ortak pagination/tag/empty/badge/breadcrumb bileşenleri; admin CSS/JS; public/user/company liste view'ları ve pagination bağlantıları; blog yazar alanı/migration; ilgili testler ve QA script/kanıtları.
