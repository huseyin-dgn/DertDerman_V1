from pathlib import Path
import re

path = Path("accounts/test_email_verification.py")

if not path.exists():
    raise SystemExit(
        "accounts/test_email_verification.py bulunamadı. "
        "Scripti manage.py ile aynı klasörde çalıştır."
    )

text = path.read_text(encoding="utf-8")

pattern = re.compile(
    r'(^    def test_verified_user_can_login\(self\):\n)'
    r'(.*?)(?=^    def |\Z)',
    re.MULTILINE | re.DOTALL,
)

match = pattern.search(text)

if not match:
    raise SystemExit(
        "test_verified_user_can_login fonksiyonu bulunamadı."
    )

block = match.group(0)

if 'reverse("dashboard:home")' in block:
    print("Bu test zaten dashboard:home bekliyor.")
    print("Dosya:", path)
    raise SystemExit(0)

if 'reverse("accounts:email_verification_pending")' not in block:
    print("Fonksiyon bulundu ama beklenen eski yönlendirme ifadesi yok.")
    print("Mevcut fonksiyon:")
    print(block)
    raise SystemExit(1)

new_block = block.replace(
    'reverse("accounts:email_verification_pending")',
    'reverse("dashboard:home")',
)

text = text[:match.start()] + new_block + text[match.end():]
path.write_text(text, encoding="utf-8")

print("Düzeltildi:", path)
print("Sadece test_verified_user_can_login fonksiyonu değiştirildi.")
print("Artık beklenen yönlendirme: dashboard:home")
