from pathlib import Path
from datetime import datetime
import shutil
import sys

BASE = Path.cwd()
PACKAGE = Path(__file__).resolve().parent

required = [
    BASE / "manage.py",
    BASE / "accounts/models.py",
    BASE / "accounts/forms.py",
    BASE / "adminx/urls.py",
    BASE / "templates/layouts/admin_base.html",
    BASE / "templates/adminx/user_detail.html",
]

missing = [str(path) for path in required if not path.exists()]

if missing:
    print("HATA: Script proje kökünde çalıştırılmalı.")
    print("Eksik yollar:")
    for item in missing:
        print(" -", item)
    sys.exit(1)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_root = BASE / f"_backup_permanent_closure_{stamp}"
backup_root.mkdir(parents=True, exist_ok=True)


def backup_file(path):
    relative = path.relative_to(BASE)
    destination = backup_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)

def write_package_file(relative):
    source = PACKAGE / relative
    target = BASE / relative

    target.parent.mkdir(parents=True, exist_ok=True)

    if source.resolve() == target.resolve():
        print("ZATEN YERİNDE:", relative)
        return

    if target.exists():
        backup_file(target)

    shutil.copy2(source, target)

    print("YAZILDI:", relative)

def patch_file(path, transform):
    original = path.read_text(encoding="utf-8")
    updated = transform(original)

    if updated == original:
        print("DEĞİŞMEDİ:", path.relative_to(BASE))
        return

    backup_file(path)
    path.write_text(updated, encoding="utf-8")
    print("GÜNCELLENDİ:", path.relative_to(BASE))


for relative in [
    Path("adminx/permanent_closure.py"),
    Path("adminx/templatetags/__init__.py"),
    Path("adminx/templatetags/moderation_alerts.py"),
    Path("templates/adminx/_permanent_closure_alert.html"),
    Path("templates/adminx/_permanent_closure_action.html"),
    Path("templates/adminx/closed_user_list.html"),
]:
    write_package_file(relative)


def patch_models(source):
    if "is_permanently_closed = models.BooleanField" in source:
        return source

    marker = "    def __str__(self):"

    if marker not in source:
        raise RuntimeError(
            "accounts/models.py içinde 'def __str__' bulunamadı."
        )

    lines = [
        "    # Kalıcı hesap kapatma bilgileri.",
        "    # Satır silinmez; e-posta/kullanıcı adı rezervasyonu ve audit izi korunur.",
        "    is_permanently_closed = models.BooleanField(",
        "        default=False,",
        "        db_index=True,",
        "    )",
        "    permanently_closed_at = models.DateTimeField(",
        "        null=True,",
        "        blank=True,",
        "    )",
        "    permanently_closed_by = models.ForeignKey(",
        '        "self",',
        "        null=True,",
        "        blank=True,",
        "        on_delete=models.SET_NULL,",
        '        related_name="permanent_closures_performed",',
        "    )",
        "    permanent_closure_reason = models.TextField(",
        "        blank=True,",
        "    )",
        "    permanent_closure_snapshot = models.JSONField(",
        "        default=dict,",
        "        blank=True,",
        "    )",
        "",
    ]

    block = "\n".join(lines)

    return source.replace(
        marker,
        block + marker,
        1,
    )


patch_file(
    BASE / "accounts/models.py",
    patch_models,
)


def patch_forms(source):
    if "PERMANENTLY_CLOSED_LOGIN_ERROR" not in source:
        target = (
            'USER_LOGIN_ERROR = '
            '"Giriş bilgileriniz doğrulanamadı. Kullanıcı adınızı ve şifrenizi kontrol edin."'
        )

        if target not in source:
            raise RuntimeError(
                "accounts/forms.py içinde USER_LOGIN_ERROR bulunamadı."
            )

        replacement = "\n".join([
            target,
            "",
            "PERMANENTLY_CLOSED_LOGIN_ERROR = (",
            '    "Hesabınız kalıcı olarak kapatılmıştır. "',
            '    "Bu hesapla tekrar giriş yapılamaz. "',
            '    "Kararla ilgili destek için DertDerman ile iletişime geçebilirsiniz."',
            ")",
        ])

        source = source.replace(
            target,
            replacement,
            1,
        )

    if "code=\"permanently_closed\"" not in source:
        marker = "    def confirm_login_allowed(self, user):"

        if marker not in source:
            raise RuntimeError(
                "UserAuthenticationForm confirm_login_allowed bulunamadı."
            )

        clean_lines = [
            "    def clean(self):",
            "        username = (",
            "            self.data.get(self.add_prefix(\"username\"))",
            "            or \"\"",
            "        ).strip()",
            "",
            "        password = (",
            "            self.data.get(self.add_prefix(\"password\"))",
            "            or \"\"",
            "        )",
            "",
            "        # Hesap durumunu yalnız doğru parola girilmişse açıklarız.",
            "        # Yanlış parola ile hesap durumunun keşfedilmesini önler.",
            "        if username and password:",
            "            candidate = (",
            "                User.objects",
            "                .filter(username__iexact=username)",
            "                .only(",
            "                    \"pk\",",
            "                    \"password\",",
            "                    \"is_permanently_closed\",",
            "                )",
            "                .first()",
            "            )",
            "",
            "            if (",
            "                candidate",
            "                and candidate.is_permanently_closed",
            "                and candidate.check_password(password)",
            "            ):",
            "                raise ValidationError(",
            "                    PERMANENTLY_CLOSED_LOGIN_ERROR,",
            "                    code=\"permanently_closed\",",
            "                )",
            "",
            "        return super().clean()",
            "",
        ]

        source = source.replace(
            marker,
            "\n".join(clean_lines) + marker,
            1,
        )

    if "Bu e-posta adresiyle yeni hesap oluşturulamaz." not in source:
        marker = "    def save(self, commit=True):"

        if marker not in source:
            raise RuntimeError(
                "RegisterForm save metodu bulunamadı."
            )

        method_lines = [
            "    def clean_email(self):",
            "        email = (",
            "            self.cleaned_data.get(\"email\")",
            "            or \"\"",
            "        ).strip()",
            "",
            "        normalized = User.objects.normalize_email(email)",
            "",
            "        existing = (",
            "            User.objects",
            "            .filter(email__iexact=normalized)",
            "            .only(",
            "                \"pk\",",
            "                \"is_permanently_closed\",",
            "            )",
            "            .first()",
            "        )",
            "",
            "        if existing:",
            "            if existing.is_permanently_closed:",
            "                raise forms.ValidationError(",
            "                    \"Bu e-posta adresiyle yeni hesap oluşturulamaz.\"",
            "                )",
            "",
            "            raise forms.ValidationError(",
            "                \"Bu e-posta adresi zaten kullanımda.\"",
            "            )",
            "",
            "        return normalized",
            "",
        ]

        source = source.replace(
            marker,
            "\n".join(method_lines) + marker,
            1,
        )

    return source


patch_file(
    BASE / "accounts/forms.py",
    patch_forms,
)


def patch_admin_urls(source):
    import_anchor = "from . import blog_views, content_views, views"

    if "from . import permanent_closure" not in source:
        if import_anchor not in source:
            raise RuntimeError(
                "adminx/urls.py import anchor bulunamadı."
            )

        source = source.replace(
            import_anchor,
            import_anchor + "\nfrom . import permanent_closure",
            1,
        )

    if 'name="closed_user_list"' not in source:
        route_anchor = (
            '    path("bildirimler/", views.notifications, name="notifications"),'
        )

        if route_anchor not in source:
            raise RuntimeError(
                "adminx/urls.py bildirim route anchor bulunamadı."
            )

        routes = "\n".join([
            "    path(",
            '        "kullanicilar/kapatilanlar/",',
            "        permanent_closure.closed_user_list,",
            '        name="closed_user_list",',
            "    ),",
            "    path(",
            '        "kullanicilar/<int:pk>/kalici-kapat/",',
            "        permanent_closure.permanently_close_user,",
            '        name="permanently_close_user",',
            "    ),",
            "",
        ])

        source = source.replace(
            route_anchor,
            routes + route_anchor,
            1,
        )

    return source


patch_file(
    BASE / "adminx/urls.py",
    patch_admin_urls,
)


def patch_admin_base(source):
    if "Kapatılan Hesaplar" not in source:
        anchor = '<div class="ad-header-actions">'

        if anchor not in source:
            raise RuntimeError(
                "admin_base.html ad-header-actions bulunamadı."
            )

        button = (
            '<a class="secondary-action" '
            'href="{% url \'adminx:closed_user_list\' %}">'
            'Kapatılan Hesaplar</a>'
        )

        source = source.replace(
            anchor,
            anchor + button,
            1,
        )

    if "_permanent_closure_alert.html" not in source:
        if "</body>" not in source:
            raise RuntimeError(
                "admin_base.html </body> bulunamadı."
            )

        source = source.replace(
            "</body>",
            "{% include 'adminx/_permanent_closure_alert.html' %}\n</body>",
            1,
        )

    return source


patch_file(
    BASE / "templates/layouts/admin_base.html",
    patch_admin_base,
)


def patch_user_detail(source):
    if "_permanent_closure_action.html" in source:
        return source

    marker = "{% endblock %}"
    position = source.rfind(marker)

    if position == -1:
        raise RuntimeError(
            "user_detail.html son endblock bulunamadı."
        )

    include = (
        "\n{% include 'adminx/_permanent_closure_action.html' %}\n\n"
    )

    return (
        source[:position]
        + include
        + source[position:]
    )


patch_file(
    BASE / "templates/adminx/user_detail.html",
    patch_user_detail,
)

print()
print("Kurulum yamaları tamamlandı.")
print("Yedek klasörü:", backup_root)
print()
print("Şimdi çalıştırın:")
print("  python manage.py makemigrations accounts")
print("  python manage.py migrate")
print("  python manage.py check")
print("  python manage.py runserver")
