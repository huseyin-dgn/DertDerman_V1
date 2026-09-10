from django.utils.text import slugify


COMPANY_CATEGORY_NAMES = (
    "Bankacılık ve Finans",
    "Telekomünikasyon",
    "E-Ticaret",
    "Market ve Perakende",
    "Kargo ve Lojistik",
    "Ulaşım",
    "Otomotiv",
    "Elektronik ve Teknoloji",
    "İnternet Servis Sağlayıcıları",
    "Sigorta",
    "Eğitim",
    "Sağlık",
    "Turizm ve Seyahat",
    "Yeme İçme",
    "Giyim ve Moda",
    "Ev ve Yaşam",
    "Enerji",
    "Kamu Hizmetleri",
    "Dijital Hizmetler",
    "Diğer",
)


def seed_company_categories(category_model):
    created = 0
    for name in COMPANY_CATEGORY_NAMES:
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
        created += 1
    return created
