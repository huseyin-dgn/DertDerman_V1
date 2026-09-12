from pathlib import Path
import shutil
import sys

ROOT = Path.cwd()

services_path = ROOT / "notifications" / "services.py"
settings_path = ROOT / "config" / "settings.py"
env_example = ROOT / ".env.example"

for required in (ROOT / "manage.py", services_path, settings_path):
    if not required.exists():
        print(f"HATA: Eksik dosya: {required}")
        print("Bu script manage.py bulunan dertderman klasöründe çalıştırılmalı.")
        sys.exit(1)

backup_dir = ROOT / ".stage5-finish-backup"
backup_dir.mkdir(exist_ok=True)

# ----------------------------
# notifications/services.py
# ----------------------------
services = services_path.read_text(encoding="utf-8")
original_services = services

has_created = (
    "notification, created = Notification.objects.get_or_create(" in services
)
has_schedule = (
    "schedule_notification_email(notification)" in services
)

if not has_created:
    old = "    notification, _ = Notification.objects.get_or_create(\n"
    new = "    notification, created = Notification.objects.get_or_create(\n"

    if old not in services:
        print(
            "HATA: services.py içinde beklenen get_or_create satırı bulunamadı."
        )
        print("Hiçbir değişiklik yapılmadı.")
        sys.exit(1)

    services = services.replace(old, new, 1)

if not has_schedule:
    old = """    return notification


def send_admins(**event):
"""
    new = """    if created:
        # AŞAMA 5:
        # Site içi bildirim business event'in kalıcı kaydıdır.
        # E-posta yalnız politika uygunsa ve transaction commit edildikten
        # sonra best-effort olarak gönderilir.
        from .transactional_email import schedule_notification_email

        schedule_notification_email(notification)

    return notification


def send_admins(**event):
"""

    if old not in services:
        print(
            "HATA: services.py içinde 'return notification' patch noktası bulunamadı."
        )
        print("Hiçbir değişiklik yapılmadı.")
        sys.exit(1)

    services = services.replace(old, new, 1)

if services != original_services:
    shutil.copy2(
        services_path,
        backup_dir / "services.py",
    )
    services_path.write_text(services, encoding="utf-8")
    print("OK: notifications/services.py tamamlandı.")
else:
    print("OK: notifications/services.py zaten doğru durumda.")

# ----------------------------
# config/settings.py
# ----------------------------
settings = settings_path.read_text(encoding="utf-8")

if "TRANSACTIONAL_EMAILS_ENABLED" not in settings:
    marker = (
        'EMAIL_SENDING_ENABLED = _env_bool('
        '"EMAIL_SENDING_ENABLED", default=False)\n'
    )

    if marker not in settings:
        print(
            "HATA: settings.py içinde EMAIL_SENDING_ENABLED satırı bulunamadı."
        )
        sys.exit(1)

    replacement = marker + """TRANSACTIONAL_EMAILS_ENABLED = _env_bool(
    "TRANSACTIONAL_EMAILS_ENABLED",
    default=True,
)
"""

    shutil.copy2(
        settings_path,
        backup_dir / "settings.py",
    )

    settings = settings.replace(
        marker,
        replacement,
        1,
    )
    settings_path.write_text(
        settings,
        encoding="utf-8",
    )
    print("OK: config/settings.py tamamlandı.")
else:
    print("OK: config/settings.py zaten doğru durumda.")

# ----------------------------
# .env.example
# ----------------------------
if env_example.exists():
    env_text = env_example.read_text(encoding="utf-8")

    if "TRANSACTIONAL_EMAILS_ENABLED" not in env_text:
        shutil.copy2(
            env_example,
            backup_dir / ".env.example",
        )

        anchor = "EMAIL_SENDING_ENABLED=False"

        if anchor in env_text:
            env_text = env_text.replace(
                anchor,
                anchor + "\nTRANSACTIONAL_EMAILS_ENABLED=True",
                1,
            )
        else:
            env_text = (
                env_text.rstrip()
                + "\nTRANSACTIONAL_EMAILS_ENABLED=True\n"
            )

        env_example.write_text(
            env_text,
            encoding="utf-8",
        )
        print("OK: .env.example tamamlandı.")
    else:
        print("OK: .env.example zaten doğru durumda.")

print()
print("AŞAMA 5 eksik kurulum tamamlandı.")
print("Migration YOK.")
print("Yedek:", backup_dir)
print()
print("Şimdi çalıştır:")
print("python manage.py check")
print("python manage.py test notifications.test_transactional_email")
print("python manage.py test notifications")
print("python manage.py test accounts")
