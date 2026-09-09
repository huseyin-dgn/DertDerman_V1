# Bildirim Merkezi

## Yapı ve kapsam

Projede `notifications` uygulaması kayıtlıydı ancak kişisel Notification modeli ve ekranları yoktu. Çalışan `CompanyNotification` / `CompanyNotificationRead` yapısı korundu; geçmiş kayıtlar taşınmadı veya yeniden oluşturulmadı.

- `notifications.Notification`: USER ve ADMIN için alıcı kullanıcı, rol kapsamı, olay türü, başlık, mesaj, ilgili şikayet veya şirket, olay anahtarı, oluşturulma/okunma zamanı ve `is_read`.
- `CompanyNotification`: mevcut şirket olay kaydı; `message` ve nullable benzersiz `event_key` ile genişletildi.
- `CompanyNotificationRead`: mevcut kullanıcı başına okundu kayıtları aynen kullanılır. Bir yetkilinin okuması diğer yetkilinin bildirimini okundu yapmaz.
- Şikayet ilişkisi varsa şirket kimliği kişisel bildirimde ayrıca kopyalanmaz. `target_url` serbest metin olarak saklanmaz; izin verilen Django route'larından sunucuda üretilir.
- Django messages anlık işlem geri bildirimidir; kalıcı bildirimlerle karıştırılmadı.

## Olaylar

| Gerçek olay | USER | COMPANY | ADMIN |
| --- | --- | --- | --- |
| Şikayet oluşturma | Şikayetiniz alındı | Yeni şikayet | Moderasyon bekliyor |
| Şikayet yayınlama | Şikayetiniz yayınlandı | Şikayet yayınlandı | — |
| Şikayet reddetme | Şikayetiniz reddedildi | Yönetim güncellemesi | — |
| CompanyResponse oluşturma | Şirket şikayetinize cevap verdi | — | — |
| Şikayet RESOLVED geçişi | Şikayetiniz çözüldü | Şikayet çözüldü | — |
| Diğer şikayet durum değişikliği | Durum güncellemesi | Yönetim güncellemesi | — |
| Şikayet başlığı/açıklaması değişikliği | — | Şikayet güncellendi | — |
| Yeni PENDING şirket başvurusu | — | — | Yeni şirket başvurusu |
| Şirket başvurusu kararı | — | Onay/ret bildirimi | — |
| Şirket aktiflik/doğrulama değişikliği veya mevcut arşiv işlemi | — | Kritik yönetim işlemi | — |

Mevcut sistemde ayrı bir USER yanıt oluşturma akışı bulunmuyor; bu görevde yeni bir yanıt özelliği eklenmedi. Dahili şirket notları USER bildirimi üretmez. ADMIN olayları olay anındaki aktif ADMIN hesaplarına iletilir; yeni bir admin hesabına geçmiş olaylar geriye dönük kopyalanmaz.

İş akışı entegrasyonları mevcut şirket olay sinyallerinde, `notifications/events.py` içinde ve atomik moderasyon servisindedir. QuerySet.update sinyal çalıştırmadığı için mevcut moderasyon yolu olay servisini açıkça çağırmaya devam eder. Gelecekte eklenecek bulk update iş akışları da olay servisini çağırmalıdır.

## Ekranlar ve sıralama

| Rol | Liste | Sayfa boyutu | Sıralama |
| --- | --- | --- | --- |
| USER | `/bildirimler/` | 8 | Okunmamış önce; grup içinde `-created_at, -pk` |
| COMPANY | `/sirket-panel/bildirimler/` | 8 | `-created_at, -pk` |
| ADMIN | `/yonetim/bildirimler/` | 10 | `-created_at, -pk` |

ADMIN dashboard önizlemesi en fazla 5 kayıt gösterir. Diğer admin listelerinin mevcut 5/sayfa standardı korunur. Ortak pagination bileşeni kullanılır; geçersiz sayfalar 500 üretmez.

USER ekranı renk kodlu ikonlar ve ayrı kartlar; COMPANY mevcut kurumsal operasyon listesi; ADMIN daha sıkı satırlar ve doğrudan inceleme bağlantıları kullanır. Üç ekranın ikonlu boş durumları vardır.

USER ve ADMIN başlığına okunmamış sayacı eklendi. COMPANY'nin mevcut başlık/sidemenu sayacı korunarak aynı kapsam sorgusuna bağlandı. Kişisel sayaç ihtiyaç halinde bir kez hesaplanan COUNT sorgusudur. Liste ilişkileri `select_related`, şirket okundu kontrolü `Exists` ile yüklenir.

## Okundu ve güvenlik

- Tekli ve tümünü okundu işlemleri POST + CSRF gerektirir. GET listeleme ve ilgili sayfaya yönlenme okundu durumunu değiştirmez.
- USER yalnız kendi USER bildirimlerini görür. Şikayet sahipliği değişmişse eski alıcının erişimi kesilir.
- COMPANY yalnız seçili şirket kapsamındaki bildirimleri görür. Her istekte aktif kullanıcı, geçerli/aktif üyelik ve approved/active/verified/unarchived şirket şartları korunur. Bildirimdeki şikayet başka şirkete taşınmışsa kayıt görünmez.
- ADMIN yalnız kendisine gönderilmiş ADMIN bildirimlerini okur. Mevcut sistem/aktivite günlüğü ayrı kalır.
- Başka alıcıya/şirkete ait bildirim kimliği ile tekli GET/POST erişimi 404; yanlış rol 403; anonim kullanıcı girişe yönlenir.
- Mark-all USER/ADMIN'de alıcıya, COMPANY'de seçili şirkete ve mevcut kullanıcıya uygulanır. İstemciden gönderilen şirket/alıcı/URL/next alanları kapsamı değiştirmez.
- Başlık ve mesajlar template autoescape ile gösterilir. Bildirim bağlantıları server-side reverse kullanır; arbitrary redirect URL kabul edilmez.

## Tekrar koruması

Olay anahtarı + alıcı + rol benzersizliği aynı olayın yeniden iletiminde kopya kişisel bildirim oluşturmaz. Şirket olaylarında da olay anahtarı benzersizdir. Durum geçişleri yeni olay sayılır; örneğin RESOLVED → PUBLISHED → RESOLVED iki meşru çözüm bildirimi üretir. No-op save yeni bildirim üretmez. Atomik moderasyon/başvuru kararlarının tekrar POST'u ikinci karar veya ikinci bildirim üretmez.

Mevcut şikayet ve şirket yanıtı formlarında bir gönderim anahtarı yoktu. Aynı kullanıcı/şirket/şikayet ve aynı içerikle **30 saniye içinde** yinelenen POST mevcut kaydı döndürür. Bu kontrollü tekrar penceresi sonrasında aynı içerikli yeni başvuru/yanıt yeni olaydır; meşru tekrarlar kalıcı unique constraint ile engellenmez. Şirket yanıtında şikayet satırı, bireysel başvuruda kullanıcı satırı mevcut atomik işlem içinde kilitlenir. Bildirim üretimi iş akışı transaction'ına katılır; rollback bildirimleri de geri alır.

## Mevcut tasarımların korunması

Auth formları/rol ayrımı, blog, intro, public şirketler düzeni ve panel CSS dosyaları değiştirilmedi. Başlık rozetleri ve ADMIN önizlemesi mevcut panel iskeletlerine küçük entegrasyonlardır. Kişisel şikayet detayına, bildirimden gelen kullanıcının cevabı okuyabilmesi için mevcut tasarım sınıflarıyla şirket yanıtları eklendi; dahili notlar eklenmedi.

Başlangıç hash'leriyle karşılaştırılan 54 korunan dosya aynı kaldı. Migration öncesi yedekle karşılaştırmada mevcut şirket, üyelik, şikayet, yanıt, şirket bildirimi ve önceki okundu satırları korundu. [Kapsam/veri denetimi](notification-qa/scope-and-data-audit.json).

## Migration ve doğrulama

Uygulanan migration'lar:

1. `companies.0005_companynotification_event_key_and_more`
2. `notifications.0001_initial`

Yerel veritabanı migration öncesinde geçici dizine yedeklendi. Migration'lar hem boş test veritabanında hem mevcut yerel veritabanında çalıştı. [Migration çıktısı](notification-qa/migrate.txt). `makemigrations --check --dry-run`: `No changes detected`.

- 20 yeni bildirim testi: olaylar, tekrarlar, rollback, ownership, rol ayrımı, CSRF, tekli/toplu okuma, güvenli URL, XSS, boş durum, pagination, preview ve N+1 kontrolleri.
- İlgili regresyon paketi: **121 test, OK** — [çıktı](notification-qa/related-tests.txt).
- Tam paket: **257 test, OK** — [çıktı](notification-qa/full-tests.txt).
- USER/ADMIN liste isteğinde en fazla 6, COMPANY'de en fazla 7 SQL sorgusu testle sınırlandı; sayı liste satırı sayısıyla artmıyor.
- Yerel Edge 152.0.4191.66: 375, 430, 768, 1024, 1366, 1440 genişliklerinde üç rol için 18 kontrol; taşma yok. Üç boş durum, ikinci sayfa, tekli/toplu okuma ve sayaç güncellemesi kontrol edildi. Uygulama içi Browser bağlantısı mevcut olmadığından headless Edge kullanıldı; gerçek mobil cihaz testi yapılmadı.

İstenen üç senaryo hem Django testinde hem gerçek tarayıcı form gönderimlerinde doğrulandı:

1. **USER complaint published → sahibi USER'a yayın bildirimi.**
2. **COMPANY response → complaint owner USER'a yanıt bildirimi → kendi detayında yanıtı okuma.**
3. **New company application → ADMIN bildirimi → başvuru detayına erişim.**

[Tarayıcı sonuçları](notification-qa/results.json), [ekran görüntüleri](notification-qa/), [tekrar çalıştırılabilir QA](../scripts/qa_notifications.py).
