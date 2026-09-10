import unicodedata

from django.core.exceptions import ValidationError


BLOCKED_EMOJI = {"🖕", "🔞", "💩", "🍆", "🍑"}
VARIATION = {"\ufe0e", "\ufe0f"}
ZWJ = "\u200d"


def _emoji_base(char):
    value = ord(char)
    return (
        0x1F000 <= value <= 0x1FAFF
        or 0x2600 <= value <= 0x27BF
        or 0x2300 <= value <= 0x23FF
    )


def validate_single_emoji(value):
    value = (value or "").strip()
    if not value or len(value) > 32 or any(char.isspace() for char in value):
        raise ValidationError("Tek bir geçerli emoji seçin.")
    if value in BLOCKED_EMOJI:
        raise ValidationError("Bu sembol tepki olarak kullanılamaz.")
    regional = [char for char in value if 0x1F1E6 <= ord(char) <= 0x1F1FF]
    if regional:
        if len(value) != 2 or len(regional) != 2:
            raise ValidationError("Tek bir geçerli emoji seçin.")
        return value

    parts = value.split(ZWJ)
    if any(not part for part in parts):
        raise ValidationError("Tek bir geçerli emoji seçin.")
    for part in parts:
        bases = []
        for char in part:
            code = ord(char)
            if char in VARIATION or 0x1F3FB <= code <= 0x1F3FF or unicodedata.combining(char):
                continue
            if not _emoji_base(char):
                raise ValidationError("Tek bir geçerli emoji seçin.")
            bases.append(char)
        if len(bases) != 1:
            raise ValidationError("Tek bir geçerli emoji seçin.")
    return value
