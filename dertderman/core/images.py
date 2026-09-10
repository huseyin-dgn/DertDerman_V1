from io import BytesIO
from uuid import uuid4

from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, UnidentifiedImageError


MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_IMAGE_EDGE = 1600
ALLOWED_IMAGE_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}


def secure_uploaded_image(value, *, supplied_mime=None):
    """Decode and safely re-encode an uploaded raster image."""
    if not value or not isinstance(value, UploadedFile):
        return value
    if value.size > MAX_IMAGE_BYTES:
        raise ValidationError("Görsel en fazla 3 MB olabilir.")
    try:
        value.seek(0)
        image = Image.open(value)
        image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError("Geçerli bir JPEG, PNG veya WebP görsel yükleyin.")
    image_format = (image.format or "").upper()
    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise ValidationError("Yalnızca JPEG, PNG veya WebP görseller kabul edilir.")
    extension, expected_mime = ALLOWED_IMAGE_FORMATS[image_format]
    supplied_mime = (supplied_mime or getattr(value, "content_type", "") or "").lower()
    if supplied_mime != expected_mime:
        raise ValidationError("Görsel dosyasının içerik türü doğrulanamadı.")

    image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
    output = BytesIO()
    if image_format == "JPEG":
        image.convert("RGB").save(output, "JPEG", quality=88, optimize=True)
    elif image_format == "PNG":
        mode = "RGBA" if "A" in image.getbands() else "RGB"
        image.convert(mode).save(output, "PNG", optimize=True)
    else:
        mode = "RGBA" if "A" in image.getbands() else "RGB"
        image.convert(mode).save(output, "WEBP", quality=88, method=6)
    return ContentFile(output.getvalue(), name=f"{uuid4().hex}.{extension}")
