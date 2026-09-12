from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path.cwd()
BACKUP_ROOT = ROOT / ".stage2-backups"
PACKAGE_ROOT = Path(__file__).resolve().parent


class PatchError(RuntimeError):
    pass


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise PatchError(
            f"{path}: expected exactly one patch target, found {count}. "
            "No write was performed for this patch."
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: Path, marker: str, addition: str) -> None:
    text = path.read_text(encoding="utf-8")
    if addition.strip() in text:
        return
    count = text.count(marker)
    if count != 1:
        raise PatchError(f"{path}: marker not found uniquely ({count}).")
    path.write_text(text.replace(marker, marker + addition, 1), encoding="utf-8")


def backup(path: Path) -> None:
    rel = path.relative_to(ROOT)
    dest = BACKUP_ROOT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(path, dest)


def copy_new(rel: str) -> None:
    src = PACKAGE_ROOT / rel
    dest = ROOT / rel
    if dest.exists():
        raise PatchError(f"Refusing to overwrite existing new file: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def main() -> None:
    required = [
        ROOT / "manage.py",
        ROOT / "accounts/forms.py",
        ROOT / "accounts/views.py",
        ROOT / "accounts/urls.py",
        ROOT / "config/settings.py",
        ROOT / "notifications/email_service.py",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise PatchError(
            "Run this script from the dertderman directory. Missing: "
            + ", ".join(missing)
        )

    existing_new = [
        ROOT / "accounts/email_verification.py",
        ROOT / "accounts/test_email_verification.py",
        ROOT / "templates/accounts/email_verification_pending.html",
        ROOT / "templates/accounts/email_verification_confirm.html",
        ROOT / "templates/emails/base.html",
        ROOT / "templates/emails/base.txt",
        ROOT / "templates/emails/email_verification.html",
        ROOT / "templates/emails/email_verification.txt",
    ]
    if any(p.exists() for p in existing_new):
        raise PatchError(
            "Stage 2 appears to be partially applied already. Restore from "
            ".stage2-backups or remove the partial Stage 2 files before retrying."
        )

    files_to_backup = [
        ROOT / "accounts/forms.py",
        ROOT / "accounts/views.py",
        ROOT / "accounts/urls.py",
        ROOT / "config/settings.py",
    ]

    optional_test_files = [
        ROOT / "accounts/test_auth_v2.py",
        ROOT / "accounts/test_routes.py",
        ROOT / "accounts/test_history_navigation.py",
    ]
    files_to_backup.extend(p for p in optional_test_files if p.exists())

    env_example = ROOT / ".env.example"
    if env_example.exists():
        files_to_backup.append(env_example)

    for path in files_to_backup:
        backup(path)

    # settings.py
    settings_path = ROOT / "config/settings.py"
    settings_marker = '''SITE_BASE_URL = os.getenv(\n    "SITE_BASE_URL",\n    "http://127.0.0.1:8000",\n).strip().rstrip("/")\n'''
    settings_addition = '''\n\n# Verification links are valid for 24 hours by default.\nEMAIL_VERIFICATION_TIMEOUT = int(\n    os.getenv("EMAIL_VERIFICATION_TIMEOUT", "86400")\n)\n'''
    append_once(settings_path, settings_marker, settings_addition)

    if env_example.exists():
        append_once(
            env_example,
            "SITE_BASE_URL=http://127.0.0.1:8000\n",
            "\n# 24 hours, in seconds\nEMAIL_VERIFICATION_TIMEOUT=86400\n",
        )

    # forms.py
    forms_path = ROOT / "accounts/forms.py"
    replace_once(
        forms_path,
        '''PERMANENTLY_CLOSED_LOGIN_ERROR = (\n    "Hesabınız kalıcı olarak kapatılmıştır. "\n    "Bu hesapla tekrar giriş yapılamaz. "\n    "Kararla ilgili destek için DertDerman ile iletişime geçebilirsiniz."\n)\n''',
        '''PERMANENTLY_CLOSED_LOGIN_ERROR = (\n    "Hesabınız kalıcı olarak kapatılmıştır. "\n    "Bu hesapla tekrar giriş yapılamaz. "\n    "Kararla ilgili destek için DertDerman ile iletişime geçebilirsiniz."\n)\n\nUNVERIFIED_LOGIN_ERROR = (\n    "Giriş yapmadan önce e-posta adresinizi doğrulamanız gerekiyor. "\n    "Kayıt sırasında gönderilen doğrulama bağlantısını kullanın."\n)\n''',
    )
    replace_once(
        forms_path,
        '''    def confirm_login_allowed(self, user):\n        super().confirm_login_allowed(user)\n        if user.user_type != User.UserType.USER:\n            raise ValidationError(USER_LOGIN_ERROR, code="invalid_login")\n''',
        '''    def confirm_login_allowed(self, user):\n        super().confirm_login_allowed(user)\n\n        if user.user_type != User.UserType.USER:\n            raise ValidationError(USER_LOGIN_ERROR, code="invalid_login")\n\n        # This check runs only after Django has authenticated the supplied\n        # credentials, so account verification state is not exposed to a\n        # caller who does not know the password.\n        if not user.is_verified:\n            raise ValidationError(\n                UNVERIFIED_LOGIN_ERROR,\n                code="email_unverified",\n            )\n''',
    )

    # views.py
    views_path = ROOT / "accounts/views.py"
    replace_once(
        views_path,
        "from django.contrib import messages\n",
        "import logging\n\nfrom django.contrib import messages\n",
    )
    replace_once(
        views_path,
        "from django.views.decorators.http import require_POST\n",
        "from django.views.decorators.http import require_POST, require_http_methods\n",
    )
    replace_once(
        views_path,
        "from core.decorators import role_required\n",
        "from core.decorators import role_required\nfrom notifications.email_service import EmailServiceError\n",
    )
    replace_once(
        views_path,
        '''from .forms import (\n    ProfileUpdateForm,\n    RegisterForm,\n    UserAuthenticationForm,\n)\n''',
        '''from .email_verification import (\n    resolve_email_verification_token,\n    send_verification_email,\n    verify_email_verification_token,\n)\nfrom .forms import (\n    ProfileUpdateForm,\n    RegisterForm,\n    UserAuthenticationForm,\n)\n''',
    )
    replace_once(
        views_path,
        "from .redirects import safe_role_next\n\n\ndef role_redirect_url(user):\n",
        "from .redirects import safe_role_next\n\n\nlogger = logging.getLogger(__name__)\n\n\ndef role_redirect_url(user):\n",
    )
    replace_once(
        views_path,
        '''    def form_valid(\n        self,\n        form,\n    ):\n        user = form.save()\n\n        login(\n            self.request,\n            user,\n        )\n\n        return redirect(\n            "dashboard:home"\n        )\n\n\n@method_decorator(\n    never_cache,\n    name="dispatch",\n)\nclass SecureLoginView(LoginView):\n''',
        '''    def form_valid(\n        self,\n        form,\n    ):\n        # RegisterForm persists is_verified=False. The user is deliberately\n        # NOT logged in here; verification must complete first.\n        user = form.save()\n\n        try:\n            result = send_verification_email(user)\n        except EmailServiceError as exc:\n            logger.error(\n                "Verification email delivery failed: user_id=%s exception_type=%s",\n                user.pk,\n                exc.__class__.__name__,\n            )\n            messages.warning(\n                self.request,\n                (\n                    "Hesabınız oluşturuldu ancak doğrulama e-postası şu anda "\n                    "gönderilemedi. Lütfen destek ekibiyle iletişime geçin."\n                ),\n            )\n        else:\n            if result.status == "sent":\n                messages.success(\n                    self.request,\n                    "Doğrulama bağlantısını e-posta adresinize gönderdik.",\n                )\n            else:\n                messages.warning(\n                    self.request,\n                    (\n                        "Hesabınız oluşturuldu ancak e-posta gönderimi şu anda "\n                        "devre dışı. Doğrulama tamamlanmadan giriş yapamazsınız."\n                    ),\n                )\n\n        return redirect(\n            "accounts:email_verification_pending"\n        )\n\n\n@never_cache\ndef email_verification_pending(request):\n    if request.user.is_authenticated:\n        return redirect(role_redirect_url(request.user))\n\n    return render(\n        request,\n        "accounts/email_verification_pending.html",\n    )\n\n\n@never_cache\n@require_http_methods(["GET", "POST"])\ndef email_verification_confirm(request, token):\n    if request.method == "GET":\n        token_valid = (\n            resolve_email_verification_token(token)\n            is not None\n        )\n\n        return render(\n            request,\n            "accounts/email_verification_confirm.html",\n            {"token_valid": token_valid},\n            status=200 if token_valid else 400,\n        )\n\n    user = verify_email_verification_token(token)\n\n    if user is None:\n        return render(\n            request,\n            "accounts/email_verification_confirm.html",\n            {"token_valid": False},\n            status=400,\n        )\n\n    messages.success(\n        request,\n        "E-posta adresiniz doğrulandı. Artık giriş yapabilirsiniz.",\n    )\n\n    return redirect("accounts:login")\n\n\n@method_decorator(\n    never_cache,\n    name="dispatch",\n)\nclass SecureLoginView(LoginView):\n''',
    )

    # urls.py
    urls_path = ROOT / "accounts/urls.py"
    replace_once(
        urls_path,
        '''    account_entry,\n    invalidate_history_session,\n    profile,\n''',
        '''    account_entry,\n    email_verification_confirm,\n    email_verification_pending,\n    invalidate_history_session,\n    profile,\n''',
    )
    replace_once(
        urls_path,
        '''    path("kayit/", RegisterView.as_view(), name="register"),\n    path("giris/", SecureLoginView.as_view(), name="login"),\n''',
        '''    path("kayit/", RegisterView.as_view(), name="register"),\n    path(\n        "eposta-dogrulama-bekleniyor/",\n        email_verification_pending,\n        name="email_verification_pending",\n    ),\n    path(\n        "eposta-dogrula/<str:token>/",\n        email_verification_confirm,\n        name="email_verification_confirm",\n    ),\n    path("giris/", SecureLoginView.as_view(), name="login"),\n''',
    )

    # Compatibility updates for the project's pre-existing auth regression tests.
    auth_test = ROOT / "accounts/test_auth_v2.py"
    if auth_test.exists():
        replace_once(
            auth_test,
            "from django.test import Client, TestCase\n",
            "from django.test import Client, TestCase, override_settings\n",
        )
        replace_once(
            auth_test,
            "password=cls.password, user_type=role)\n            for role in ['USER', 'COMPANY', 'ADMIN']}",
            "password=cls.password, user_type=role, is_verified=(role == 'USER'))\n            for role in ['USER', 'COMPANY', 'ADMIN']}",
        )
        replace_once(
            auth_test,
            "from companies.models import Company, CompanyMembership\n",
            "from companies.models import Company, CompanyCategory, CompanyMembership\n",
        )
        replace_once(
            auth_test,
            "        cls.company = Company.objects.create(name='Auth V2 Company', is_verified=True)\n",
            "        cls.company_category = CompanyCategory.objects.create(name='Auth V2 Category')\n        cls.company = Company.objects.create(name='Auth V2 Company', is_verified=True, category=cls.company_category)\n",
        )
        replace_once(
            auth_test,
            "    def test_user_registration_ignores_all_privileged_fields_and_creates_no_company(self):\n",
            "    @override_settings(EMAIL_SENDING_ENABLED=False)\n    def test_user_registration_ignores_all_privileged_fields_and_creates_no_company(self):\n",
        )
        replace_once(
            auth_test,
            "            self.assertRedirects(response, reverse('dashboard:home'))\n",
            "            self.assertRedirects(response, reverse('accounts:email_verification_pending'))\n            self.assertNotIn('_auth_user_id', client.session)\n",
        )
        replace_once(
            auth_test,
            "            'company_name': 'New Auth Company', 'first_name': 'Deniz', 'last_name': 'Yılmaz',\n",
            "            'company_name': 'New Auth Company', 'category': self.company_category.pk, 'first_name': 'Deniz', 'last_name': 'Yılmaz',\n",
        )

    routes_test = ROOT / "accounts/test_routes.py"
    if routes_test.exists():
        replace_once(
            routes_test,
            "from django.test import Client, TestCase\n",
            "from django.test import Client, TestCase, override_settings\n",
        )
        replace_once(
            routes_test,
            "                password=cls.password, user_type=role,\n",
            "                password=cls.password, user_type=role,\n                is_verified=(role == User.UserType.USER),\n",
        )
        replace_once(
            routes_test,
            "    def test_register_login_logout_smoke_and_role_logins(self):\n",
            "    @override_settings(EMAIL_SENDING_ENABLED=False)\n    def test_register_login_logout_smoke_and_role_logins(self):\n",
        )
        replace_once(
            routes_test,
            '''        self.assertRedirects(client.post("/hesap/kayit/", {\n            "username": "route-smoke-user", "email": "route-smoke@example.com",\n            "password1": self.password, "password2": self.password,\n            "selected_avatar": "avatar-1",\n        }), "/panel/")\n        self.assertEqual(client.get("/panel/").status_code, 200)\n        self.assertRedirects(client.post("/hesap/cikis/"), "/")\n        self.assertRedirects(client.get("/panel/"), "/hesap/giris/?next=/panel/")\n        self.assertRedirects(client.post("/hesap/giris/", {\n            "username": "route-smoke-user", "password": self.password,\n        }), "/panel/")\n''',
            '''        self.assertRedirects(client.post("/hesap/kayit/", {\n            "username": "route-smoke-user", "email": "route-smoke@example.com",\n            "password1": self.password, "password2": self.password,\n            "selected_avatar": "avatar-1",\n        }), "/hesap/eposta-dogrulama-bekleniyor/")\n        self.assertNotIn("_auth_user_id", client.session)\n        self.assertRedirects(client.get("/panel/"), "/hesap/giris/?next=/panel/")\n\n        account = User.objects.get(username="route-smoke-user")\n        account.is_verified = True\n        account.save(update_fields=["is_verified"])\n\n        self.assertRedirects(client.post("/hesap/giris/", {\n            "username": "route-smoke-user", "password": self.password,\n        }), "/panel/")\n        self.assertEqual(client.get("/panel/").status_code, 200)\n''',
        )

    history_test = ROOT / "accounts/test_history_navigation.py"
    if history_test.exists():
        replace_once(
            history_test,
            '''            username="history-user", email="history-user@example.com",\n            password=PASSWORD, user_type=User.UserType.USER,\n''',
            '''            username="history-user", email="history-user@example.com",\n            password=PASSWORD, user_type=User.UserType.USER, is_verified=True,\n''',
        )
        replace_once(
            history_test,
            '''                password=PASSWORD, user_type=role,\n            )\n            for role in User.UserType.values\n''',
            '''                password=PASSWORD, user_type=role,\n                is_verified=(role == User.UserType.USER),\n            )\n            for role in User.UserType.values\n''',
        )

    # New Stage 2 files.
    for rel in [
        "accounts/email_verification.py",
        "accounts/test_email_verification.py",
        "templates/accounts/email_verification_pending.html",
        "templates/accounts/email_verification_confirm.html",
        "templates/emails/base.html",
        "templates/emails/base.txt",
        "templates/emails/email_verification.html",
        "templates/emails/email_verification.txt",
    ]:
        copy_new(rel)

    print("AŞAMA 2 uygulandı.")
    print(f"Yedekler: {BACKUP_ROOT}")
    print("Sonraki adım: python manage.py check")


if __name__ == "__main__":
    main()
