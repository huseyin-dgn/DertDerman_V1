from django.test import SimpleTestCase

from .models import EmailDelivery
from .provider_identifiers import (
    PROVIDER_MESSAGE_ID_MAX_LENGTH,
    ProviderMessageIdValidationError,
    validate_provider_message_id,
)


class ProviderMessageIdValidatorTests(SimpleTestCase):
    def test_model_and_validator_share_capacity(self):
        field = EmailDelivery._meta.get_field("provider_message_id")

        self.assertEqual(field.max_length, PROVIDER_MESSAGE_ID_MAX_LENGTH)

    def test_valid_opaque_id_is_returned_unchanged(self):
        provider_message_id = "resend-style_ID:Case-Sensitive"

        self.assertIs(
            validate_provider_message_id(provider_message_id),
            provider_message_id,
        )

    def test_non_string_values_are_rejected(self):
        for value in (None, 123, object()):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ProviderMessageIdValidationError):
                    validate_provider_message_id(value)

    def test_empty_and_surrounding_whitespace_are_rejected(self):
        for value in ("", "   ", " id", "id ", "id value", "id  value"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ProviderMessageIdValidationError):
                    validate_provider_message_id(value)

    def test_control_style_whitespace_is_rejected(self):
        for value in (
            "id\x00value",
            "id\rvalue",
            "id\nvalue",
            "id\tvalue",
            "id\u2028value",
            "id\u200bvalue",
        ):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ProviderMessageIdValidationError):
                    validate_provider_message_id(value)

    def test_exact_capacity_is_accepted_unchanged(self):
        provider_message_id = "x" * PROVIDER_MESSAGE_ID_MAX_LENGTH

        self.assertEqual(
            validate_provider_message_id(provider_message_id),
            provider_message_id,
        )

    def test_over_capacity_is_rejected_without_truncation(self):
        prefix = "x" * PROVIDER_MESSAGE_ID_MAX_LENGTH

        for provider_message_id in (prefix + "A", prefix + "B"):
            with self.subTest(suffix=provider_message_id[-1]):
                with self.assertRaises(ProviderMessageIdValidationError):
                    validate_provider_message_id(provider_message_id)

    def test_exception_does_not_include_raw_invalid_id(self):
        provider_message_id = "private-provider-id\nsecret"

        with self.assertRaises(ProviderMessageIdValidationError) as context:
            validate_provider_message_id(provider_message_id)

        self.assertNotIn(provider_message_id, str(context.exception))
