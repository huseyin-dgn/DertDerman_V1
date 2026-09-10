COMPANY_AVATAR_KEYS = tuple(f"company-{number}" for number in range(1, 9))
COMPANY_AVATAR_CHOICES = (("", "Baş harf / ikon"),) + tuple(
    (key, f"Kurumsal simge {number}") for number, key in enumerate(COMPANY_AVATAR_KEYS, 1)
)


def is_valid_company_avatar(value):
    return value in COMPANY_AVATAR_KEYS or value == ""
