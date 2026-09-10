USER_AVATAR_KEYS = tuple(f"avatar-{number}" for number in range(1, 21))
USER_AVATAR_CHOICES = tuple((key, f"Avatar {number}") for number, key in enumerate(USER_AVATAR_KEYS, 1))


def is_valid_user_avatar(value):
    return value in USER_AVATAR_KEYS
