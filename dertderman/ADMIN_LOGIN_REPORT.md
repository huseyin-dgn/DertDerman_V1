# Custom admin login

`/yonetim/giris/` eklendi. Sade, animasyonsuz mavi/beyaz form DertDerman, Yönetim Paneli, Yetkili Girişi, kullanıcı adı, şifre ve giriş düğmesini içerir. Public admin kayıt akışı eklenmedi.

## Akış ve güvenlik

- Anonim `/yonetim/` → `/yonetim/giris/?next=/yonetim/`. Diğer mevcut yönetim view'ları da aynı admin giriş noktasına yönlenir. Public kullanıcı/şirket giriş yönlendirmesi değişmedi.
- Django `AuthenticationForm` mevcut `authenticate()` ve password hashing mekanizmasını kullanır. Formun `confirm_login_allowed()` adımında aktiflik ve `user_type == ADMIN` şartı doğrulanır. Ardından Django `LoginView` mevcut `login()` ve session mekanizmasıyla oturum açar.
- ADMIN hesabı staff/superuser bayrakları olmadan kabul edilir. USER/COMPANY/UNKNOWN hesapları, iki bayrak açık olsa bile admin girişinden oturum açamaz.
- Yanlış şifre, olmayan hesap, pasif hesap ve uygun olmayan rol için aynı mesaj: “Yönetim paneli giriş bilgileri doğrulanamadı.”
- Başarı adresi daima `/yonetim/`; GET/POST ile gönderilen `next` kullanılmaz. Dış URL ve yanlış role ait iç URL yönlendirmeleri engellenir.
- Giriş POST'u CSRF korumalıdır. Girişte session anahtarı değişir. Logout mevcut POST + CSRF davranışını korur; eski session replay yönetim alanına erişemez.
- Mevcut ADMIN oturumu giriş sayfasından yönetim ana sayfasına gider; mevcut diğer roller 403 alır. Yönetim yetki kontrolü sunucudadır. Giriş formu, hatalı giriş yanıtı, yönetim yönlendirmeleri ve yetkili private yanıtlar never_cache/no-store korumasındadır.
- `/django-admin/` custom 404 + HTTP 404 olarak kalır. Catch-all, membership, publication ve nesne yetkilendirme kuralları değiştirilmedi.

## Testler

- `python manage.py check`: temiz.
- `python manage.py test`: **141/141 geçti** (135 mevcut test + 6 yeni admin auth testi). Eski admin anonim yönlendirme beklentileri yeni giriş adresine güncellendi.
- `python manage.py makemigrations --check --dry-run`: No changes detected.
- Headless Chromium: normal, hatalı ve boş form; 320/360/768/1024/1440 px, toplam 15 kontrol. Yatay taşma, JS hatası, dış istek veya static asset hatası yok. Form etiketleri, klavyeyle şifre göster/gizle, JS kapalı kullanım ve animasyon bulunmaması doğrulandı.
- QA çıktıları: `C:/Users/hdgn5/AppData/Local/Temp/dd-admin-login-qa/`.

## Bu görevde değişen dosyalar

- `adminx/auth_views.py` (yeni)
- `adminx/decorators.py` (yeni)
- `adminx/urls.py`
- `adminx/views.py` (yalnızca admin giriş dekoratörü entegrasyonu)
- `adminx/blog_views.py` (yalnızca admin giriş dekoratörü entegrasyonu)
- `adminx/content_views.py` (yalnızca admin giriş dekoratörü entegrasyonu)
- `core/decorators.py` (isteğe bağlı login_url parametresi)
- `templates/adminx/login.html` (yeni)
- `static/css/pages.css` (yalnızca admin giriş formu stilleri)
- `adminx/test_auth.py` (yeni)
- `adminx/tests.py`
- `adminx/test_content.py`
- `accounts/test_routes.py`
- `accounts/tests.py`
- `ADMIN_LOGIN_REPORT.md` (yeni)
