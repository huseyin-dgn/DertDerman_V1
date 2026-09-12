from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path.cwd()
BACKUP_ROOT = ROOT / ".stage2-backups"


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


NEW_FILES = {'accounts/email_verification.py': 'from hashlib import sha256\n\nfrom django.conf import settings\nfrom django.core import signing\nfrom django.db import transaction\nfrom django.template.loader import render_to_string\nfrom django.urls import reverse\nfrom django.utils.crypto import constant_time_compare\n\nfrom notifications.email_service import (\n    EmailConfigurationError,\n    send_email,\n)\n\nfrom .models import User\n\n\nTOKEN_SALT = "accounts.email-verification.v1"\nMAX_TOKEN_LENGTH = 1024\n\n\nclass EmailVerificationConfigurationError(RuntimeError):\n    """Raised when verification email settings are incomplete."""\n\n\ndef _verification_state_digest(user: User) -> str:\n    email = (user.email or "").strip().casefold()\n    material = "\\0".join(\n        (\n            str(user.pk),\n            email,\n            user.password or "",\n            "1" if user.is_verified else "0",\n        )\n    )\n    return sha256(material.encode("utf-8")).hexdigest()\n\n\ndef make_email_verification_token(user: User) -> str:\n    if not user.pk:\n        raise ValueError("User must be saved before creating a verification token.")\n\n    if user.user_type != User.UserType.USER:\n        raise ValueError("Email verification token is only valid for USER accounts.")\n\n    if user.is_verified:\n        raise ValueError("Verified users do not need a verification token.")\n\n    value = f"{user.pk}:{_verification_state_digest(user)}"\n    return signing.TimestampSigner(salt=TOKEN_SALT).sign(value)\n\n\ndef _token_max_age() -> int:\n    try:\n        value = int(getattr(settings, "EMAIL_VERIFICATION_TIMEOUT", 86400))\n    except (TypeError, ValueError) as exc:\n        raise EmailVerificationConfigurationError(\n            "EMAIL_VERIFICATION_TIMEOUT must be an integer number of seconds."\n        ) from exc\n\n    if value <= 0:\n        return value\n\n    return value\n\n\ndef resolve_email_verification_token(\n    token: str,\n    *,\n    for_update: bool = False,\n) -> User | None:\n    token = (token or "").strip()\n\n    if not token or len(token) > MAX_TOKEN_LENGTH:\n        return None\n\n    signer = signing.TimestampSigner(salt=TOKEN_SALT)\n\n    try:\n        unsigned = signer.unsign(\n            token,\n            max_age=_token_max_age(),\n        )\n    except signing.BadSignature:\n        return None\n\n    try:\n        user_id_text, _digest = unsigned.split(":", 1)\n        user_id = int(user_id_text)\n    except (TypeError, ValueError):\n        return None\n\n    queryset = User.objects.filter(\n        pk=user_id,\n        user_type=User.UserType.USER,\n        is_active=True,\n    )\n\n    if for_update:\n        queryset = queryset.select_for_update()\n\n    user = queryset.first()\n\n    if not user or user.is_verified:\n        return None\n\n    expected = f"{user.pk}:{_verification_state_digest(user)}"\n\n    if not constant_time_compare(unsigned, expected):\n        return None\n\n    return user\n\n\n@transaction.atomic\ndef verify_email_verification_token(token: str) -> User | None:\n    user = resolve_email_verification_token(\n        token,\n        for_update=True,\n    )\n\n    if user is None:\n        return None\n\n    user.is_verified = True\n    user.save(update_fields=("is_verified",))\n    return user\n\n\ndef build_email_verification_url(user: User) -> str:\n    base_url = (\n        getattr(settings, "SITE_BASE_URL", "")\n        or ""\n    ).strip().rstrip("/")\n\n    if not base_url:\n        raise EmailVerificationConfigurationError(\n            "SITE_BASE_URL is required for verification links."\n        )\n\n    token = make_email_verification_token(user)\n    path = reverse(\n        "accounts:email_verification_confirm",\n        kwargs={"token": token},\n    )\n    return f"{base_url}{path}"\n\n\ndef send_verification_email(user: User):\n    if user.user_type != User.UserType.USER:\n        raise ValueError("Verification email is only valid for USER accounts.")\n\n    if user.is_verified:\n        raise ValueError("Verified users do not need a verification email.")\n\n    verification_url = build_email_verification_url(user)\n\n    context = {\n        "user": user,\n        "verification_url": verification_url,\n        "support_email": getattr(settings, "SUPPORT_EMAIL", "destek@dertderman.com"),\n        "support_phone": getattr(settings, "SUPPORT_PHONE", "+90 850 532 2206"),\n        "support_hours": getattr(settings, "SUPPORT_HOURS", "Hafta içi 09:00 - 18:00"),\n    }\n\n    html_body = render_to_string(\n        "emails/email_verification.html",\n        context,\n    )\n    text_body = render_to_string(\n        "emails/email_verification.txt",\n        context,\n    )\n\n    event_key = (\n        "account:email-verification:"\n        f"{user.pk}:"\n        f"{_verification_state_digest(user)[:20]}"\n    )\n\n    try:\n        return send_email(\n            recipient_email=user.email,\n            subject="E-posta adresinizi doğrulayın | DertDerman",\n            html_body=html_body,\n            text_body=text_body,\n            event_key=event_key,\n        )\n    except EmailConfigurationError:\n        raise\n', 'accounts/test_email_verification.py': 'from types import SimpleNamespace\nfrom unittest.mock import patch\n\nfrom django.test import Client, TestCase, override_settings\nfrom django.urls import reverse\n\nfrom accounts.email_verification import (\n    make_email_verification_token,\n    resolve_email_verification_token,\n    send_verification_email,\n)\nfrom accounts.forms import UNVERIFIED_LOGIN_ERROR\nfrom accounts.models import User\n\n\nclass EmailVerificationTests(TestCase):\n    password = "EmailVerification2026!"\n\n    def create_user(self, **overrides):\n        data = {\n            "username": "verify-user",\n            "email": "verify-user@example.com",\n            "password": self.password,\n            "user_type": User.UserType.USER,\n            "is_verified": False,\n        }\n        data.update(overrides)\n        return User.objects.create_user(**data)\n\n    @patch("accounts.views.send_verification_email")\n    def test_registration_creates_unverified_user_without_login(self, send_verification):\n        send_verification.return_value = SimpleNamespace(status="sent")\n\n        response = self.client.post(\n            reverse("accounts:register"),\n            {\n                "username": "new-verification-user",\n                "email": "new-verification-user@example.com",\n                "password1": self.password,\n                "password2": self.password,\n                "selected_avatar": "avatar-1",\n            },\n        )\n\n        self.assertRedirects(\n            response,\n            reverse("accounts:email_verification_pending"),\n        )\n        self.assertNotIn("_auth_user_id", self.client.session)\n\n        user = User.objects.get(username="new-verification-user")\n        self.assertFalse(user.is_verified)\n        send_verification.assert_called_once_with(user)\n\n    def test_unverified_user_cannot_login_even_with_correct_password(self):\n        user = self.create_user()\n\n        response = self.client.post(\n            reverse("accounts:login"),\n            {\n                "username": user.username,\n                "password": self.password,\n            },\n        )\n\n        self.assertContains(response, UNVERIFIED_LOGIN_ERROR)\n        self.assertNotIn("_auth_user_id", self.client.session)\n\n    def test_verified_user_can_login(self):\n        user = self.create_user(is_verified=True)\n\n        response = self.client.post(\n            reverse("accounts:login"),\n            {\n                "username": user.username,\n                "password": self.password,\n            },\n        )\n\n        self.assertRedirects(response, reverse("dashboard:home"))\n\n    def test_get_confirmation_page_never_verifies_account(self):\n        user = self.create_user()\n        token = make_email_verification_token(user)\n\n        response = self.client.get(\n            reverse(\n                "accounts:email_verification_confirm",\n                kwargs={"token": token},\n            )\n        )\n\n        self.assertEqual(response.status_code, 200)\n        user.refresh_from_db()\n        self.assertFalse(user.is_verified)\n        self.assertContains(response, "E-postamı Doğrula")\n\n    def test_post_confirmation_verifies_account(self):\n        user = self.create_user()\n        token = make_email_verification_token(user)\n        route = reverse(\n            "accounts:email_verification_confirm",\n            kwargs={"token": token},\n        )\n\n        response = self.client.post(route)\n\n        self.assertRedirects(response, reverse("accounts:login"))\n        user.refresh_from_db()\n        self.assertTrue(user.is_verified)\n\n    def test_token_is_single_use(self):\n        user = self.create_user()\n        token = make_email_verification_token(user)\n        route = reverse(\n            "accounts:email_verification_confirm",\n            kwargs={"token": token},\n        )\n\n        self.assertEqual(self.client.post(route).status_code, 302)\n        self.assertEqual(self.client.get(route).status_code, 400)\n        self.assertIsNone(resolve_email_verification_token(token))\n\n    def test_tampered_token_is_rejected(self):\n        user = self.create_user()\n        token = make_email_verification_token(user)\n        tampered = f"{token}x"\n\n        response = self.client.get(\n            reverse(\n                "accounts:email_verification_confirm",\n                kwargs={"token": tampered},\n            )\n        )\n\n        self.assertEqual(response.status_code, 400)\n        user.refresh_from_db()\n        self.assertFalse(user.is_verified)\n\n    @override_settings(EMAIL_VERIFICATION_TIMEOUT=-1)\n    def test_expired_token_is_rejected(self):\n        user = self.create_user()\n        token = make_email_verification_token(user)\n        self.assertIsNone(resolve_email_verification_token(token))\n\n    def test_verification_post_requires_csrf(self):\n        user = self.create_user()\n        token = make_email_verification_token(user)\n        route = reverse(\n            "accounts:email_verification_confirm",\n            kwargs={"token": token},\n        )\n\n        client = Client(enforce_csrf_checks=True)\n        self.assertEqual(client.get(route).status_code, 200)\n        self.assertEqual(client.post(route).status_code, 403)\n\n        user.refresh_from_db()\n        self.assertFalse(user.is_verified)\n\n    @override_settings(\n        SITE_BASE_URL="https://dertderman.com",\n        SUPPORT_EMAIL="destek@dertderman.com",\n        SUPPORT_PHONE="+90 850 532 2206",\n        SUPPORT_HOURS="Hafta içi 09:00 - 18:00",\n    )\n    @patch("accounts.email_verification.send_email")\n    def test_email_uses_fixed_site_base_url_html_and_text(self, send_email):\n        user = self.create_user()\n        send_email.return_value = SimpleNamespace(status="sent")\n\n        send_verification_email(user)\n\n        kwargs = send_email.call_args.kwargs\n        self.assertEqual(kwargs["recipient_email"], user.email)\n        self.assertIn("https://dertderman.com/hesap/eposta-dogrula/", kwargs["html_body"])\n        self.assertIn("https://dertderman.com/hesap/eposta-dogrula/", kwargs["text_body"])\n        self.assertIn("DertDerman", kwargs["html_body"])\n        self.assertIn("DertDerman", kwargs["text_body"])\n        self.assertNotIn(user.email, kwargs["event_key"])\n', 'templates/accounts/email_verification_pending.html': '{% extends \'layouts/auth_base.html\' %}\n{% block title %}E-posta Doğrulama | DertDerman{% endblock %}\n{% block auth_variant %}ax-user-login{% endblock %}\n{% block content %}\n<main class="ax-layout" id="main-content">\n  <aside class="ax-story" aria-labelledby="verification-story-title">\n    <div class="ax-story-inner">\n      <p class="ax-eyebrow">HESAP GÜVENLİĞİ</p>\n      <h2 id="verification-story-title">Son bir adım kaldı.</h2>\n      <p class="ax-story-lead">Hesabınızı kullanmadan önce e-posta adresinizi doğrulamanız gerekiyor.</p>\n      <div class="ax-kept-visual">{% include \'components/auth_visual.html\' %}</div>\n    </div>\n  </aside>\n  <div class="ax-form-area">\n    <section class="ax-card" aria-labelledby="auth-title">\n      {% include \'auth/messages.html\' %}\n      <header class="ax-heading">\n        <span class="ax-role">E-posta doğrulama</span>\n        <h1 id="auth-title">Gelen kutunuzu kontrol edin</h1>\n        <p>Size gönderilen doğrulama bağlantısını açın. Bağlantıdaki sayfada ayrıca “E-postamı Doğrula” düğmesine basmadan hesabınız doğrulanmaz.</p>\n      </header>\n      <div class="ax-alternative">\n        <span>Doğrulamayı tamamladınız mı?</span>\n        <a href="{% url \'accounts:login\' %}">Giriş Yap {% include \'components/icon.html\' %}</a>\n      </div>\n      <p class="ax-crosslink">E-posta ulaşmadıysa şimdilik <a href="mailto:destek@dertderman.com">destek@dertderman.com</a> üzerinden destek alabilirsiniz.</p>\n    </section>\n  </div>\n</main>\n{% endblock %}\n', 'templates/accounts/email_verification_confirm.html': '{% extends \'layouts/auth_base.html\' %}\n{% block title %}E-posta Doğrulama | DertDerman{% endblock %}\n{% block auth_variant %}ax-user-login{% endblock %}\n{% block content %}\n<main class="ax-layout" id="main-content">\n  <aside class="ax-story" aria-labelledby="verification-story-title">\n    <div class="ax-story-inner">\n      <p class="ax-eyebrow">HESAP GÜVENLİĞİ</p>\n      <h2 id="verification-story-title">E-posta adresinizi doğrulayın.</h2>\n      <p class="ax-story-lead">Bu adım hesabınızın e-posta adresine gerçekten erişebildiğinizi doğrular.</p>\n      <div class="ax-kept-visual">{% include \'components/auth_visual.html\' %}</div>\n    </div>\n  </aside>\n  <div class="ax-form-area">\n    <section class="ax-card" aria-labelledby="auth-title">\n      <header class="ax-heading">\n        <span class="ax-role">E-posta doğrulama</span>\n        {% if token_valid %}\n          <h1 id="auth-title">Doğrulamayı tamamlayın</h1>\n          <p>Bu sayfayı açmanız hesabı doğrulamaz. Aşağıdaki düğmeye bastığınızda doğrulama işlemi tamamlanır.</p>\n        {% else %}\n          <h1 id="auth-title">Bağlantı geçersiz</h1>\n          <p>Bu doğrulama bağlantısının süresi dolmuş, daha önce kullanılmış veya bağlantı değiştirilmiş olabilir.</p>\n        {% endif %}\n      </header>\n\n      {% if token_valid %}\n        <form method="post" class="ax-form">\n          {% csrf_token %}\n          <button type="submit" class="ax-submit">\n            <span>E-postamı Doğrula</span>\n            {% include \'components/icon.html\' %}\n          </button>\n        </form>\n      {% endif %}\n\n      <div class="ax-alternative">\n        <span>Hesabınız zaten doğrulandı mı?</span>\n        <a href="{% url \'accounts:login\' %}">Giriş Yap {% include \'components/icon.html\' %}</a>\n      </div>\n    </section>\n  </div>\n</main>\n{% endblock %}\n', 'templates/emails/base.html': '<!doctype html>\n<html lang="tr">\n  <body style="margin:0;padding:0;background:#f4f8fc;font-family:Arial,Helvetica,sans-serif;color:#172033;">\n    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f4f8fc;padding:32px 12px;">\n      <tr>\n        <td align="center">\n          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:620px;background:#ffffff;border:1px solid #dfe8f3;border-radius:16px;overflow:hidden;">\n            <tr>\n              <td style="background:#1d5fa7;padding:24px 32px;color:#ffffff;font-size:24px;font-weight:700;">DertDerman</td>\n            </tr>\n            <tr>\n              <td style="padding:32px;line-height:1.65;font-size:16px;">\n                {% block email_content %}{% endblock %}\n              </td>\n            </tr>\n            <tr>\n              <td style="border-top:1px solid #e6edf5;padding:22px 32px;color:#667085;font-size:13px;line-height:1.7;">\n                <strong style="color:#1d5fa7;">DertDerman</strong><br>\n                {{ support_email }}<br>\n                {{ support_phone }}<br>\n                {{ support_hours }}\n              </td>\n            </tr>\n          </table>\n        </td>\n      </tr>\n    </table>\n  </body>\n</html>\n', 'templates/emails/base.txt': '{% block email_content %}{% endblock %}\n\nDertDerman\n{{ support_email }}\n{{ support_phone }}\n{{ support_hours }}\n', 'templates/emails/email_verification.html': '{% extends \'emails/base.html\' %}\n{% block email_content %}\n<p style="margin-top:0;">Merhaba{% if user.first_name %} {{ user.first_name }}{% endif %},</p>\n<p>DertDerman hesabınızı kullanmaya başlamadan önce e-posta adresinizi doğrulamanız gerekiyor.</p>\n<p style="margin:28px 0;">\n  <a href="{{ verification_url }}" style="display:inline-block;background:#1d5fa7;color:#ffffff;text-decoration:none;font-weight:700;padding:13px 22px;border-radius:8px;">E-posta Doğrulama Sayfasını Aç</a>\n</p>\n<p>Güvenlik nedeniyle bağlantıyı açmak tek başına hesabınızı doğrulamaz. Açılan sayfada <strong>E-postamı Doğrula</strong> düğmesine basmanız gerekir.</p>\n<p>Bu hesabı siz oluşturmadıysanız bu e-postayı dikkate almayabilirsiniz.</p>\n{% endblock %}\n', 'templates/emails/email_verification.txt': '{% extends \'emails/base.txt\' %}\n{% block email_content %}Merhaba{% if user.first_name %} {{ user.first_name }}{% endif %},\n\nDertDerman hesabınızı kullanmaya başlamadan önce e-posta adresinizi doğrulamanız gerekiyor.\n\nDoğrulama sayfası:\n{{ verification_url }}\n\nGüvenlik nedeniyle bağlantıyı açmak tek başına hesabınızı doğrulamaz. Açılan sayfada "E-postamı Doğrula" düğmesine basmanız gerekir.\n\nBu hesabı siz oluşturmadıysanız bu e-postayı dikkate almayabilirsiniz.{% endblock %}\n'}

def copy_new(rel: str) -> None:
    dest = ROOT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Current recovery case may already contain a partial copy of this file.
    # Back it up once before writing the canonical Stage 2 package content.
    if dest.exists():
        rel_path = dest.relative_to(ROOT)
        backup_dest = BACKUP_ROOT / "_partial_new_files" / rel_path
        backup_dest.parent.mkdir(parents=True, exist_ok=True)
        if not backup_dest.exists():
            shutil.copy2(dest, backup_dest)
    dest.write_text(NEW_FILES[rel], encoding="utf-8")


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

    # Recovery mode: existing partial Stage 2 files are allowed.


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

    print("AŞAMA 2 recovery tamamlandı.")
    print(f"Yedekler: {BACKUP_ROOT}")
    print("Sonraki adım: python manage.py check")


if __name__ == "__main__":
    main()
