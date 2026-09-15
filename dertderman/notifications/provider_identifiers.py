import unicodedata


PROVIDER_MESSAGE_ID_MAX_LENGTH = 255


class ProviderMessageIdValidationError(ValueError):
    """Raised when a provider message ID is unsafe to persist or correlate."""


class ProviderMessageOwnershipError(RuntimeError):
    """Raised when one provider message ID is owned by multiple deliveries."""

    code = "provider_message_ownership_conflict"

    def __init__(self):
        super().__init__("Provider message ownership conflict.")


def validate_provider_message_id(provider_message_id: str) -> str:
    """Return an opaque provider message ID unchanged after strict validation."""
    if not isinstance(provider_message_id, str):
        raise ProviderMessageIdValidationError("Invalid provider message id.")
    if not provider_message_id or provider_message_id != provider_message_id.strip():
        raise ProviderMessageIdValidationError("Invalid provider message id.")
    if len(provider_message_id) > PROVIDER_MESSAGE_ID_MAX_LENGTH:
        raise ProviderMessageIdValidationError("Invalid provider message id.")
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs"}
        or character.isspace()
        for character in provider_message_id
    ):
        raise ProviderMessageIdValidationError("Invalid provider message id.")
    return provider_message_id
