from pathlib import Path
from datetime import datetime
import shutil
import sys

BASE = Path(__file__).resolve().parent
BACKUP_DIR = BASE / f"_backup_content_report_notifications_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

def fail(message):
    print(f"\nHATA: {message}")
    sys.exit(1)

def backup(path):
    rel = path.relative_to(BASE)
    target = BACKUP_DIR / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)

def patch(path, transform):
    if not path.exists():
        fail(f"Dosya bulunamadı: {path}")
    source = path.read_text(encoding="utf-8")
    updated = transform(source)
    if updated == source:
        print(f"DEĞİŞİKLİK YOK: {path.relative_to(BASE)}")
        return
    backup(path)
    path.write_text(updated, encoding="utf-8")
    print(f"GÜNCELLENDİ: {path.relative_to(BASE)}")

def patch_notification_services(source):
    if "def notify_content_report_decision(report):" in source:
        return source

    marker = "\ndef notify_admins_company_report(report):\n"
    if marker not in source:
        fail("notifications/services.py içinde notify_admins_company_report bulunamadı.")

    block = '''
def notify_content_report_decision(report):
    """İçerik raporu sonuçlandığında raporu gönderen kullanıcıya bilgi verir."""

    if report.status == "RESOLVED":
        return send(
            recipient=report.reporter,
            scope="USER",
            kind=Notification.Type.CONTENT_REPORT,
            event_key=f"content-report:{report.pk}:resolved:reporter",
            title="İçerik raporunuz sonuçlandırıldı.",
            message=(
                "Gönderdiğiniz içerik raporunda topluluk kurallarına "
                "aykırılık tespit edildi ve gerekli işlem uygulandı."
            ),
            content_report=report,
        )

    if report.status == "REJECTED":
        return send(
            recipient=report.reporter,
            scope="USER",
            kind=Notification.Type.CONTENT_REPORT,
            event_key=f"content-report:{report.pk}:rejected:reporter",
            title="İçerik raporunuz sonuçlandırıldı.",
            message=(
                "Yönetim incelemesinde raporlanan içerikte doğrulanmış "
                "bir topluluk kuralı ihlali bulunmadı."
            ),
            content_report=report,
        )

    if report.status == "ABUSIVE":
        return send(
            recipient=report.reporter,
            scope="USER",
            kind=Notification.Type.CONTENT_REPORT,
            event_key=f"content-report:{report.pk}:abusive:reporter",
            title="Raporunuz kötüye kullanım olarak değerlendirildi.",
            message=(
                "Gönderdiğiniz içerik raporunun kötü niyetli veya asılsız "
                "olduğu tespit edildi. Bu işlem hesabınıza doğrulanmış "
                "kötüye kullanım ihlali olarak işlendi."
            ),
            content_report=report,
        )

    return None

'''
    return source.replace(marker, "\n" + block + "def notify_admins_company_report(report):\n", 1)

def patch_notification_models(source):
    old = '''        if self.content_report_id:
            return reverse(
                'adminx:report_detail',
                args=[self.content_report_id]
            )
'''
    new = '''        if self.content_report_id:
            if self.recipient_role == self.Scope.ADMIN:
                return reverse(
                    'adminx:report_detail',
                    args=[self.content_report_id]
                )

            return reverse('accounts:profile')
'''
    if new in source:
        return source
    if old not in source:
        fail("notifications/models.py içindeki content_report target_url bloğu bulunamadı.")
    return source.replace(old, new, 1)

def patch_admin_views(source):
    old_inline = '''            from notifications.services import send
            from notifications.models import Notification

            send(
                recipient=reporter,
                scope="USER",
                kind="REPORT_ABUSE",
                event_key=f"content-report:{report.pk}:abusive",
                title="Raporunuz kötüye kullanım olarak değerlendirildi.",
                message=(
                    "Gönderdiğiniz raporun kötü niyetli veya asılsız "
                    "olduğu tespit edildi. Bu işlem hesabınıza "
                    "doğrulanmış ihlal olarak işlendi."
                ),
            )
'''
    if old_inline in source:
        source = source.replace(old_inline, "", 1)

    if "notify_content_report_decision(report)" in source:
        return source

    marker = '''    # ---------------------------------------------------------
    # ADMIN MESAJI
    # ---------------------------------------------------------

    if new_status == ContentReport.Status.REVIEWING:
'''
    if marker not in source:
        fail("adminx/views.py içinde ContentReport admin mesajı bloğu bulunamadı.")

    block = '''    # Raporu gönderen kullanıcıya terminal karar bildirimi gönder.
    if new_status in {
        ContentReport.Status.RESOLVED,
        ContentReport.Status.REJECTED,
        ContentReport.Status.ABUSIVE,
    }:
        from notifications.services import notify_content_report_decision

        notify_content_report_decision(report)

'''
    return source.replace(marker, block + marker, 1)

patch(BASE / "notifications" / "services.py", patch_notification_services)
patch(BASE / "notifications" / "models.py", patch_notification_models)
patch(BASE / "adminx" / "views.py", patch_admin_views)

print("\nTamamlandı.")
print(f"Yedek klasörü: {BACKUP_DIR.name}")
print("\nŞimdi çalıştır:")
print("  python manage.py check")
print("\nMigration gerekmiyor.")
