import warnings
from io import BytesIO

from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import Post


MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_DIMENSION = 6000


class CoverImageInput(forms.ClearableFileInput):
    template_name = "blog/cover_widget.html"


class PostForm(forms.ModelForm):
    # Check the byte limit before Pillow parses anything; accept no raw SVG/HTML.
    cover_image = forms.FileField(
        label="Kapak görseli", required=False, widget=CoverImageInput,
        help_text="JPEG, PNG veya WEBP. En fazla 5 MB, 6000 px ve 16 megapiksel. Görsel güvenli biçimde WebP olarak kaydedilir.",
    )

    class Meta:
        model = Post
        fields = ("title", "excerpt", "cover_image", "content")
        widgets = {
            "excerpt": forms.Textarea(attrs={"rows": 3}),
            "content": forms.Textarea(attrs={"rows": 16}),
        }

    def clean_cover_image(self):
        upload = self.cleaned_data.get("cover_image")
        if not isinstance(upload, UploadedFile):
            return upload
        if upload.size > MAX_IMAGE_BYTES:
            raise forms.ValidationError("Görsel en fazla 5 MB olabilir.")
        raw = upload.read(MAX_IMAGE_BYTES + 1)
        if len(raw) > MAX_IMAGE_BYTES:
            raise forms.ValidationError("Görsel en fazla 5 MB olabilir.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as probe:
                    if probe.format not in {"JPEG", "PNG", "WEBP"}:
                        raise forms.ValidationError("Yalnızca JPEG, PNG ve WEBP görselleri kabul edilir.")
                    width, height = probe.size
                    if max(width, height) > MAX_IMAGE_DIMENSION or width * height > MAX_IMAGE_PIXELS:
                        raise forms.ValidationError("Görsel boyutları izin verilen sınırı aşıyor.")
                    if getattr(probe, "n_frames", 1) != 1:
                        raise forms.ValidationError("Hareketli görseller kabul edilmez.")
                    probe.verify()
                with Image.open(BytesIO(raw)) as image:
                    image.load()
                    normalized = ImageOps.exif_transpose(image).convert("RGB")
                    normalized.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                    result = BytesIO()
                    # Re-encoding drops filename, metadata and trailing payloads.
                    normalized.save(result, format="WEBP", quality=85)
            return SimpleUploadedFile("cover.webp", result.getvalue(), content_type="image/webp")
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as error:
            raise forms.ValidationError("Geçerli ve güvenli bir görsel yükleyin.") from error
