import warnings
from io import BytesIO
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from PIL import (
    Image,
    ImageOps,
    UnidentifiedImageError,
)


MAX_IMAGE_BYTES = 3 * 1024 * 1024

# Input görseli decode edilmeden önce uygulanır.
# Küçük dosya boyutuna sahip aşırı büyük sıkıştırılmış
# görsellerin RAM tüketmesini engeller.
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_DIMENSION = 6000

# Kaydedilen görselin en uzun kenarı.
MAX_IMAGE_EDGE = 1600

ALLOWED_IMAGE_FORMATS = {
    "JPEG": (
        "jpg",
        "image/jpeg",
    ),
    "PNG": (
        "png",
        "image/png",
    ),
    "WEBP": (
        "webp",
        "image/webp",
    ),
}


def _invalid_image():
    return ValidationError(
        "Geçerli ve güvenli bir JPEG, PNG veya WebP görsel yükleyin."
    )


def secure_uploaded_image(
    value,
    *,
    supplied_mime=None,
):
    """
    Decode and safely re-encode an uploaded raster image.

    Güvenlik yaklaşımı:
    - istemci dosya adına güvenilmez,
    - istemci MIME değeri gerçek formatla karşılaştırılır,
    - ham byte ve piksel/dimension limitleri uygulanır,
    - animasyon kabul edilmez,
    - EXIF orientation uygulanır,
    - metadata/trailing payload atılır,
    - güvenli UUID isimli yeni dosya üretilir.
    """

    if (
        not value
        or not isinstance(
            value,
            UploadedFile,
        )
    ):
        return value

    if value.size > MAX_IMAGE_BYTES:
        raise ValidationError(
            "Görsel en fazla 3 MB olabilir."
        )

    try:
        value.seek(0)
        raw = value.read(
            MAX_IMAGE_BYTES + 1
        )
    except (
        OSError,
        ValueError,
    ) as exc:
        raise _invalid_image() from exc

    if len(raw) > MAX_IMAGE_BYTES:
        raise ValidationError(
            "Görsel en fazla 3 MB olabilir."
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter(
                "error",
                Image.DecompressionBombWarning,
            )

            # Önce yalnız header/metadata seviyesinde
            # güvenlik limitlerini kontrol et.
            with Image.open(
                BytesIO(raw)
            ) as probe:
                image_format = (
                    probe.format
                    or ""
                ).upper()

                if (
                    image_format
                    not in ALLOWED_IMAGE_FORMATS
                ):
                    raise ValidationError(
                        "Yalnızca JPEG, PNG veya WebP "
                        "görseller kabul edilir."
                    )

                width, height = (
                    probe.size
                )

                if (
                    width <= 0
                    or height <= 0
                    or max(
                        width,
                        height,
                    )
                    > MAX_IMAGE_DIMENSION
                    or (
                        width
                        * height
                    )
                    > MAX_IMAGE_PIXELS
                ):
                    raise ValidationError(
                        "Görsel boyutları izin verilen "
                        "sınırı aşıyor."
                    )

                if (
                    getattr(
                        probe,
                        "n_frames",
                        1,
                    )
                    != 1
                ):
                    raise ValidationError(
                        "Hareketli görseller "
                        "kabul edilmez."
                    )

                probe.verify()

            (
                extension,
                expected_mime,
            ) = ALLOWED_IMAGE_FORMATS[
                image_format
            ]

            actual_supplied_mime = (
                supplied_mime
                or getattr(
                    value,
                    "content_type",
                    "",
                )
                or ""
            ).strip().lower()

            if (
                actual_supplied_mime
                != expected_mime
            ):
                raise ValidationError(
                    "Görsel dosyasının içerik "
                    "türü doğrulanamadı."
                )

            # verify() sonrası dosya tekrar açılır.
            # Yeniden encode edildiği için orijinal
            # dosya adı, metadata ve ek payloadlar
            # saklanmaz.
            with Image.open(
                BytesIO(raw)
            ) as image:
                image.load()

                normalized = (
                    ImageOps
                    .exif_transpose(
                        image
                    )
                )

                normalized.thumbnail(
                    (
                        MAX_IMAGE_EDGE,
                        MAX_IMAGE_EDGE,
                    ),
                    Image.Resampling.LANCZOS,
                )

                output = BytesIO()

                if (
                    image_format
                    == "JPEG"
                ):
                    normalized.convert(
                        "RGB"
                    ).save(
                        output,
                        "JPEG",
                        quality=88,
                        optimize=True,
                    )

                elif (
                    image_format
                    == "PNG"
                ):
                    mode = (
                        "RGBA"
                        if "A"
                        in normalized.getbands()
                        else "RGB"
                    )

                    normalized.convert(
                        mode
                    ).save(
                        output,
                        "PNG",
                        optimize=True,
                    )

                else:
                    mode = (
                        "RGBA"
                        if "A"
                        in normalized.getbands()
                        else "RGB"
                    )

                    normalized.convert(
                        mode
                    ).save(
                        output,
                        "WEBP",
                        quality=88,
                        method=6,
                    )

    except ValidationError:
        raise

    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise _invalid_image() from exc

    return ContentFile(
        output.getvalue(),
        name=(
            f"{uuid4().hex}."
            f"{extension}"
        ),
    )
