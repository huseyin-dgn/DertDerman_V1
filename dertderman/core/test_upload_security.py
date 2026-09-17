from io import BytesIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from core.images import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_EDGE,
    secure_uploaded_image,
)


def image_upload(
    *,
    name="upload.png",
    image_format="PNG",
    content_type="image/png",
    size=(32, 32),
):
    output = BytesIO()

    Image.new(
        "RGB",
        size,
        "white",
    ).save(
        output,
        image_format,
    )

    return SimpleUploadedFile(
        name,
        output.getvalue(),
        content_type=content_type,
    )


class SecureUploadedImageTests(
    SimpleTestCase
):
    def test_valid_image_is_reencoded_with_server_generated_name(self):
        upload = image_upload(
            name="../../payload.php",
        )

        result = secure_uploaded_image(
            upload,
            supplied_mime="image/png",
        )

        self.assertNotIn(
            "..",
            result.name,
        )
        self.assertNotIn(
            "/",
            result.name,
        )
        self.assertTrue(
            result.name.endswith(
                ".png"
            )
        )

        with Image.open(
            BytesIO(
                result.read()
            )
        ) as image:
            self.assertEqual(
                image.format,
                "PNG",
            )

    def test_mime_spoofing_is_rejected(self):
        upload = image_upload(
            content_type="image/jpeg",
        )

        with self.assertRaises(
            ValidationError
        ):
            secure_uploaded_image(
                upload,
                supplied_mime=(
                    "image/jpeg"
                ),
            )

    def test_non_image_payload_is_rejected(self):
        upload = SimpleUploadedFile(
            "payload.png",
            b"<script>alert(1)</script>",
            content_type="image/png",
        )

        with self.assertRaises(
            ValidationError
        ):
            secure_uploaded_image(
                upload,
                supplied_mime=(
                    "image/png"
                ),
            )

    def test_byte_limit_is_enforced_before_decode(self):
        upload = SimpleUploadedFile(
            "large.png",
            b"x" * (
                MAX_IMAGE_BYTES
                + 1
            ),
            content_type="image/png",
        )

        with self.assertRaises(
            ValidationError
        ):
            secure_uploaded_image(
                upload,
                supplied_mime=(
                    "image/png"
                ),
            )

    @patch(
        "core.images.MAX_IMAGE_PIXELS",
        100,
    )
    def test_pixel_limit_is_enforced_before_full_decode(self):
        upload = image_upload(
            size=(11, 10),
        )

        with self.assertRaises(
            ValidationError
        ):
            secure_uploaded_image(
                upload,
                supplied_mime=(
                    "image/png"
                ),
            )

    @patch(
        "core.images.MAX_IMAGE_DIMENSION",
        100,
    )
    def test_dimension_limit_is_enforced(self):
        upload = image_upload(
            size=(101, 1),
        )

        with self.assertRaises(
            ValidationError
        ):
            secure_uploaded_image(
                upload,
                supplied_mime=(
                    "image/png"
                ),
            )

    def test_large_valid_image_is_downscaled(self):
        upload = image_upload(
            size=(2000, 1000),
        )

        result = secure_uploaded_image(
            upload,
            supplied_mime="image/png",
        )

        with Image.open(
            BytesIO(
                result.read()
            )
        ) as image:
            self.assertLessEqual(
                max(image.size),
                MAX_IMAGE_EDGE,
            )
