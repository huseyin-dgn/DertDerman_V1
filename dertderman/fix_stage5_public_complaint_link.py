from pathlib import Path
import shutil
import sys

ROOT = Path.cwd()
target = ROOT / "notifications" / "transactional_email.py"
test_file = ROOT / "notifications" / "test_transactional_email.py"

for p in (ROOT / "manage.py", target, test_file):
    if not p.exists():
        print(f"HATA: Eksik dosya: {p}")
        sys.exit(1)

backup_dir = ROOT / ".stage5-public-link-backup"
backup_dir.mkdir(exist_ok=True)

text = target.read_text(encoding="utf-8")

if "from django.urls import reverse" not in text:
    marker = "from django.template.loader import render_to_string\n"
    if marker not in text:
        print("HATA: transactional_email.py import noktası bulunamadı.")
        sys.exit(1)
    text = text.replace(
        marker,
        marker + "from django.urls import reverse\n",
        1,
    )

old = '''def build_notification_target_url(notification: Notification) -> str:
    path = notification.target_url

    if not path.startswith("/"):
        raise TransactionalEmailConfigurationError(
            "Notification target must be an internal absolute path."
        )

    return f"{_site_base_url()}{path}"
'''

new = '''def _public_complaint_path(notification: Notification) -> str | None:
    complaint = notification.complaint

    if complaint is None:
        return None

    public_notification_types = {
        Notification.Type.PUBLISHED,
        Notification.Type.RESOLVED,
        "RESPONSE",
        Notification.Type.COMPANY_RESPONDED,
    }

    if notification.notification_type not in public_notification_types:
        return None

    if complaint.status not in {"PUBLISHED", "RESOLVED"}:
        return None

    if complaint.withdrawn_at is not None:
        return None

    if getattr(complaint, "removed_for_violation", False):
        return None

    if not complaint.company.is_active:
        return None

    return reverse(
        "complaints:public_detail",
        args=[complaint.pk],
    )


def build_notification_target_url(notification: Notification) -> str:
    path = (
        _public_complaint_path(notification)
        or notification.target_url
    )

    if not path.startswith("/"):
        raise TransactionalEmailConfigurationError(
            "Notification target must be an internal absolute path."
        )

    return f"{_site_base_url()}{path}"
'''

if old in text:
    shutil.copy2(target, backup_dir / "transactional_email.py")
    text = text.replace(old, new, 1)
    target.write_text(text, encoding="utf-8")
    print("OK: transactional email public şikayet linki güncellendi.")
elif "_public_complaint_path" in text:
    print("OK: transactional_email.py zaten public complaint link mantığını içeriyor.")
else:
    print("HATA: build_notification_target_url bloğu beklenen biçimde bulunamadı.")
    sys.exit(1)

tests = test_file.read_text(encoding="utf-8")

if "test_published_email_target_is_public_without_login" not in tests:
    insertion = '''
    def test_published_email_target_is_public_without_login(self):
        Complaint.objects.filter(
            pk=self.complaint.pk
        ).update(
            status=Complaint.Status.PUBLISHED
        )
        self.complaint.refresh_from_db()

        notification = self.create_notification(
            event_key="public-url:1",
        )

        url = build_notification_target_url(notification)

        self.assertEqual(
            url,
            (
                "https://dertderman.com"
                f"/sikayetler/{self.complaint.pk}/"
            ),
        )

        response = self.client.get(
            f"/sikayetler/{self.complaint.pk}/"
        )
        self.assertEqual(response.status_code, 200)

    def test_non_public_complaint_email_does_not_expose_private_detail(self):
        Complaint.objects.filter(
            pk=self.complaint.pk
        ).update(
            status=Complaint.Status.REJECTED
        )
        self.complaint.refresh_from_db()

        notification = self.create_notification(
            kind=Notification.Type.REJECTED,
            event_key="private-url:1",
            title="Şikayetiniz reddedildi.",
        )

        url = build_notification_target_url(notification)

        self.assertIn(
            f"/sikayetlerim/{self.complaint.pk}/",
            url,
        )
        self.assertNotIn(
            f"/sikayetler/{self.complaint.pk}/",
            url,
        )

'''
    anchor = '    @patch("notifications.transactional_email.send_email")\n'
    if anchor not in tests:
        print("HATA: Test ekleme noktası bulunamadı.")
        sys.exit(1)

    shutil.copy2(test_file, backup_dir / "test_transactional_email.py")
    tests = tests.replace(anchor, insertion + anchor, 1)
    test_file.write_text(tests, encoding="utf-8")
    print("OK: public link regression testleri eklendi.")
else:
    print("OK: public link regression testleri zaten mevcut.")

print()
print("Migration YOK.")
print("Yedek:", backup_dir)
print()
print("Çalıştır:")
print("python manage.py check")
print("python manage.py test notifications.test_transactional_email")
print("python manage.py test notifications")
