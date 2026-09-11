from django.urls import reverse


SECTIONS = [
    ("home", "Genel Bakış", "overview"),
    ("complaint_list", "Şikayetler", "complaint"),
    ("company_list", "Şirketler", "building"),
    ("company_application_list", "Şirket Başvuruları", "shield"),
    ("user_list", "Kullanıcılar", "users"),
    ("blog_list", "Blog", "note"),
    ("notifications", "Bildirimler", "bell"),
    ("contact_list", "İletişim Talepleri", "note"),
    ("activity", "Sistem / Aktivite", "clock"),
    ("report_list", "Raporlar", "shield"),
    ("audit_log_list", "Yönetici İşlem Geçmişi", "shield"),
    ("homepage_content", "Site İçerikleri", "settings"),
]


def admin_shell(request):
    match = request.resolver_match

    if not match or match.namespace != "adminx":
        return {}

    route = match.url_name

    parents = {
        "complaint_detail": "complaint_list",
        "complaint_publish": "complaint_list",
        "complaint_reject": "complaint_list",
        "company_edit": "company_list",
        "company_application_detail": "company_application_list",
        "user_detail": "user_list",
        "blog_edit": "blog_list",
        "blog_create": "blog_list",
        "blog_publish": "blog_list",
        "contact_detail": "contact_list",
        "contact_status": "contact_list",
        "report_detail": "report_list",
        "report_status": "report_list",
    }

    current = parents.get(route, route)

    items = [
        {
            "url": reverse(f"adminx:{name}"),
            "label": label,
            "icon": icon,
            "active": name == current,
        }
        for name, label, icon in SECTIONS
    ]

    selected = next(
        (
            item
            for item in items
            if item["active"]
        ),
        None,
    )

    return {
        "admin_navigation": items,
        "admin_section": selected,
        "admin_is_detail": route in parents,
    }