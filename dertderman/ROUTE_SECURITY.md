# Route / Session / Authorization Denetimi

Envanter Django URL resolver üzerinden çıkarıldı. URL bilmek özel alanlara erişim sağlamaz.

## Route Inventory ve Access Matrix

`login`: `/hesap/giris/?next=...` yönlendirmesi. `role`: USER → `/panel/`, COMPANY → `/sirket-panel/`, ADMIN → `/yonetim/`; UNKNOWN → `/`.

| Route | Sınıf | Anonymous | USER | COMPANY | ADMIN |
| --- | --- | --- | --- | --- | --- |
| `/` | PUBLIC | 200 | 200 | 200 | 200 |
| `/sirketler/` | PUBLIC | 200 | 200 | 200 | 200 |
| `/sirketler/<slug>/` | PUBLIC | Aktif şirket: 200, diğer: 404 | Aynı | Aynı | Aynı |
| `/sikayetler/` | PUBLIC | 200 | 200 | 200 | 200 |
| `/sikayetler/<pk>/` | PUBLIC | PUBLISHED + aktif şirket: 200, diğer: 404 | Aynı | Aynı | Aynı |
| `/hesap/` | AUTH_PAGE (yönlendirme) | login | role | role | role |
| `/hesap/giris/` | AUTH_PAGE | 200 | role | role | role |
| `/hesap/kayit/` | AUTH_PAGE | 200 | role | role | role |
| `/hesap/cikis/` | AUTH_PAGE (session sonlandırma) | POST + CSRF → `/` | Aynı | Aynı | Aynı |
| `/panel/` | USER_ONLY | login | 200 | 403 | 403 |
| `/hesap/profil/` | USER_ONLY | login | 200 | 403 | 403 |
| `/hesap/profil/duzenle/` | USER_ONLY | login | 200 | 403 | 403 |
| `/hesap/sifre-degistir/` | USER_ONLY | login | 200 | 403 | 403 |
| `/sikayet-olustur/` | USER_ONLY | login | 200 | 403 | 403 |
| `/sikayetlerim/` | USER_ONLY | login | 200 | 403 | 403 |
| `/sikayetlerim/<pk>/` | USER_ONLY | login | Sahibi: 200, diğer: 404 | 403 | 403 |
| `/sirket-panel/` | COMPANY_ONLY | login | 403 | Aktif şirkette aktif membership: 200, diğer: 403 | 403 |
| `/sirket-panel/<slug>/` | COMPANY_ONLY | login | 403 | İlgili aktif şirkette aktif membership: 200, diğer: 403 | 403 |
| `/yonetim/` | ADMIN_ONLY | login | 403 | 403 | 200 |
| `/yonetim/sikayetler/` | ADMIN_ONLY | login | 403 | 403 | 200 |
| `/yonetim/sikayetler/<pk>/` | ADMIN_ONLY | login | 403 | 403 | Kayıt varsa 200, yoksa 404 |
| `/yonetim/sikayetler/<pk>/yayinla/` | ADMIN_ONLY, POST | login / CSRF reddi | 403 | 403 | CSRF + PENDING: 302; geçersiz geçiş: 409; yok: 404 |
| `/yonetim/sikayetler/<pk>/reddet/` | ADMIN_ONLY, POST | login / CSRF reddi | 403 | 403 | CSRF + PENDING: 302; geçersiz geçiş: 409; yok: 404 |
| `/media/<path>` | TECHNICAL | DEBUG ortamında dosya servisi | Aynı | Aynı | Aynı |
| `/static/<path>` | TECHNICAL | Development staticfiles servisi; ürün URL resolver dışında | Aynı | Aynı | Aynı |
| `/django-admin/` ve alt yolları | TECHNICAL / UNUSED | 404 | 404 | 404 | 404 |
| `/admin/` ve alt yolları | TECHNICAL / UNUSED | 404 | 404 | 404 | 404 |

`blog`, `notifications`, `payments` URL listeleri boş ve ana URL yapılandırmasına bağlı değil. Başka ürün route'u bulunmadı. `django.contrib.admin` kurulu uygulama olarak kalır; URL kaydı kaldırıldığı için HTTP erişimi yoktur. Mevcut migration geçmişi değiştirilmedi.

Tablodaki okuma kodları GET içindir; logout GET 405 döndürür. Moderasyon action GET'i ADMIN için 405'tir; diğer roller önce authorization kontrolünde reddedilir. CSRF içermeyen state-changing request, authentication yönlendirmesinden önce 403 alabilir.

## Authorization ve Session

- USER profil, profil düzenleme ve şifre değiştirme artık merkezi `role_required(USER)` ile korunur. COMPANY/ADMIN için consumer profil bağlantıları kaldırıldı.
- `role_required` explicit rol eşleşmesi ister; UNKNOWN özel alanların tamamında 403 alır. Staff/superuser bayrakları ürün rol kontrollerini aşmaz.
- Complaint ownership ve aktif company/membership kısıtları backend sorgularında korunur.
- Login success URL rol tarafından belirlenir; dış URL veya başka rolün alanına verilen `next` dikkate alınmaz. Logout da `next` değerini dikkate almadan `/` adresine döner.
- Django login session anahtarını yeniler; LogoutView session'ı geçersizleştirir. Eski session cookie'sini tekrar göndermek private erişim sağlamaz.
- `SESSION_COOKIE_HTTPONLY=True`, session ve CSRF SameSite `Lax`; CSRF middleware ve form tokenları korunur. Custom session token veya URL'de session ID yoktur.

## Back / Forward ve Cache

Private HTML ve login yönlendirmeleri merkezi role decorator üzerinden `never_cache`, `no-store`, `no-cache`, `private`, `must-revalidate`, `max-age=0` ve Expires alır. Auth sayfalarında da `never_cache` korunur. Public sayfalara bu politika eklenmez.

Logout sonrası yeni HTTP isteği protected içerik döndürmez. Tarayıcının geçici görüntü snapshot'ı authorization kaynağı değildir; piksel düzeyinde snapshot davranışı için garanti verilmez. `private-page.js`, pageshow reload, history.pushState veya history.forward kullanılmaz.

## Security Code Scan

- `csrf_exempt`, `mark_safe`, `|safe`, `autoescape off`, kontrolsüz `redirect(request.GET/POST...)`: uygulama kodunda bulunmadı.
- `request.user.is_authenticated`: merkezi authentication kontrolü ve auth sayfası yönlendirmelerinde; template kullanımları sadece navigasyon içindir.
- `user_type ==`: rol bazlı başarı yönlendirmesi ve navbar sunumu; view erişimleri ayrıca backend'de korunur.
- `admin.site.urls` ve `config/urls.py` admin import'u kaldırıldı. Kurulu admin app'i erişilebilir bir URL oluşturmaz.
- Moderasyon değişiklikleri ayrı POST endpointleri, CSRF, ADMIN rolü ve koşullu PENDING güncellemesiyle sınırlıdır.

## Production Hardening Required

Local HTTP ayarları değiştirilmedi. Production için ayrıca yapılandırılacaklar:

- `DEBUG=False`; mevcut geliştirme SECRET_KEY yerine ortam/secret store yönetimi ve gerçek domainlere sınırlı `ALLOWED_HOSTS`.
- HTTPS; deployment topolojisine uygun `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True`.
- HTTPS doğrulandıktan sonra uygun HSTS süresi ve gerekiyorsa subdomain/preload politikası.
- Gerekli güvenilir HTTPS origin'leri için `CSRF_TRUSTED_ORIGINS`; reverse proxy varsa yalnızca güvenilen proxy üzerinden HTTPS header yapılandırması.
- Login/register ve diğer hassas aksiyonlar için rate limiting; audit/security logging ve moderation audit log.
- Production static/media sunumu; DEBUG dosya servisinin yerine deployment katmanı. Gizli dosyalar public media altında tutulmamalıdır.

Bu production işleri bu görevde uygulanmadı.

## Test Sonuçları

Tüm komutlar `conda run -n torch_gpu` ile çalıştırıldı:

| Komut | Sonuç |
| --- | --- |
| `python manage.py check` | Başarılı, sorun yok |
| `python manage.py test accounts` | 35 test geçti |
| `python manage.py test companies` | 14 test geçti |
| `python manage.py test complaints` | 32 test geçti |
| `python manage.py test` | 97 test geçti |
| `python manage.py makemigrations --check --dry-run` | No changes detected |

Yeni 10 erişim testi anonymous/USER/COMPANY/ADMIN/UNKNOWN matrisi, consumer profile POST yetkisi, admin route kaldırılması, login next ve session rotation, logout sonrası eski session replay, object authorization, aktif membership, publication, kayıt/login/logout smoke zinciri, CSRF ve navbar kapsamını doğrular. Browser snapshot görsel testi yapılmadı; logout sonrası yeni istek ve cache header davranışı Django test client ile doğrulandı.
