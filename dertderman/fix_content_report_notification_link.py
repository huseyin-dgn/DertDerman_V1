from pathlib import Path
from datetime import datetime
import shutil
import sys

BASE = Path(__file__).resolve().parent
BACKUP_DIR = BASE / f"_backup_content_report_link_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

def fail(message):
    print(f"\nHATA: {message}")
    sys.exit(1)

def backup(path):
    rel = path.relative_to(BASE)
    target = BACKUP_DIR / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)

def patch(path, old, new):
    if not path.exists():
        fail(f"Dosya bulunamadı: {path}")

    source = path.read_text(encoding="utf-8")

    if new in source:
        print(f"ZATEN GÜNCEL: {path.relative_to(BASE)}")
        return

    if old not in source:
        fail(f"Beklenen kod bloğu bulunamadı: {path.relative_to(BASE)}")

    backup(path)
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    print(f"GÜNCELLENDİ: {path.relative_to(BASE)}")

models_path = BASE / "notifications" / "models.py"

old_models = """        if self.content_report_id:
            if self.recipient_role == self.Scope.ADMIN:
                return reverse(
                    'adminx:report_detail',
                    args=[self.content_report_id]
                )

            return reverse('accounts:profile')
"""

new_models = """        if self.content_report_id:
            if self.recipient_role == self.Scope.ADMIN:
                return reverse(
                    'adminx:report_detail',
                    args=[self.content_report_id]
                )

            report = self.content_report
            complaint = report.complaint

            if complaint is None and report.comment_id:
                complaint = report.comment.complaint

            if (
                complaint is not None
                and complaint.status in ("PUBLISHED", "RESOLVED")
                and complaint.withdrawn_at is None
                and complaint.company.is_active
            ):
                return reverse(
                    'complaints:public_detail',
                    args=[complaint.pk]
                )

            return reverse('notifications:list')
"""

patch(models_path, old_models, new_models)

selectors_path = BASE / "notifications" / "selectors.py"

old_selectors = """    return result.select_related('company', 'complaint')
"""

new_selectors = """    return result.select_related(
        'company',
        'complaint',
        'content_report',
        'content_report__complaint',
        'content_report__complaint__company',
        'content_report__comment',
        'content_report__comment__complaint',
        'content_report__comment__complaint__company',
    )
"""

patch(selectors_path, old_selectors, new_selectors)

print("\nTamamlandı.")
print(f"Yedek klasörü: {BACKUP_DIR.name}")
print("\nŞimdi çalıştır:")
print("  python manage.py check")
print("\nMigration gerekmiyor.")
