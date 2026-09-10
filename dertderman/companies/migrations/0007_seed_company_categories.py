from django.db import migrations


CATEGORY_NAMES = (
    "Bankacılık ve Finans", "Telekomünikasyon", "E-Ticaret",
    "Market ve Perakende", "Kargo ve Lojistik", "Ulaşım", "Otomotiv",
    "Elektronik ve Teknoloji", "İnternet Servis Sağlayıcıları", "Sigorta",
    "Eğitim", "Sağlık", "Turizm ve Seyahat", "Yeme İçme", "Giyim ve Moda",
    "Ev ve Yaşam", "Enerji", "Kamu Hizmetleri", "Dijital Hizmetler", "Diğer",
)


def seed_categories(apps, schema_editor):
    from django.utils.text import slugify

    category_model = apps.get_model("companies", "CompanyCategory")
    for name in CATEGORY_NAMES:
        if category_model.objects.filter(name=name).exists():
            continue
        base_slug = slugify(name)[:140] or "kategori"
        slug = base_slug
        number = 2
        while category_model.objects.filter(slug=slug).exists():
            suffix = f"-{number}"
            slug = f"{base_slug[:140 - len(suffix)]}{suffix}"
            number += 1
        category_model.objects.create(name=name, slug=slug, is_active=True)


class Migration(migrations.Migration):
    dependencies = [("companies", "0006_company_selected_avatar")]
    operations = [migrations.RunPython(seed_categories, migrations.RunPython.noop)]
