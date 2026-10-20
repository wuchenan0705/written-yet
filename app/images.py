"""Shrink screenshots so they stay under the Claude API image limits but text stays legible."""
import io

from PIL import Image, UnidentifiedImageError

MAX_EDGE = 2000
MAX_BYTES = 4_500_000  # API limit is 5 MB per image
MAX_IMAGES = 10


class ImageError(ValueError):
    pass


def normalize(data: bytes) -> tuple[str, bytes]:
    """Return (media_type, bytes) as PNG, or JPEG if the PNG is still too large."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ImageError("看不懂這個檔案，請上傳 PNG 或 JPG 截圖。") from e
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if max(img.size) > MAX_EDGE:
        img.thumbnail((MAX_EDGE, MAX_EDGE))
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    if out.tell() <= MAX_BYTES:
        return "image/png", out.getvalue()
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return "image/jpeg", out.getvalue()
