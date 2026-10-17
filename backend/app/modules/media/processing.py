"""Pillow work. Everything here is CPU-bound and synchronous: callers run it in asyncio.to_thread."""

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PIXELS = 40_000_000  # decompression-bomb guard (a 40 MP photo is ~160 MB decoded)
# Pillow format name -> (file extension, content type)
ALLOWED_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
    "GIF": ("gif", "image/gif"),
}
VARIANT_WIDTHS = (320, 640, 1024, 1600)
OG_SIZE = (1200, 630)


class NotAnImage(Exception):
    """Undecodable, or not one of the allowed formats."""


class TooManyPixels(Exception):
    pass


@dataclass(frozen=True)
class Cleaned:
    data: bytes
    ext: str
    mime: str
    width: int
    height: int


def clean_upload(raw: bytes) -> Cleaned:
    """Verify the real format from the bytes and re-encode without metadata (EXIF, GPS, comments)."""
    try:
        img = Image.open(io.BytesIO(raw))
        fmt = img.format
        if fmt not in ALLOWED_FORMATS:
            raise NotAnImage(fmt)
        if img.width * img.height > MAX_PIXELS:
            raise TooManyPixels
        img.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise TooManyPixels from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise NotAnImage(str(exc)) from exc
    ext, mime = ALLOWED_FORMATS[fmt]
    out = io.BytesIO()
    if fmt == "GIF":
        # Re-saving drops comments; keep the animation.
        frames = getattr(img, "n_frames", 1)
        img.save(out, "GIF", save_all=frames > 1, loop=img.info.get("loop", 0), duration=img.info.get("duration", 100))
        return Cleaned(out.getvalue(), ext, mime, img.width, img.height)
    img = ImageOps.exif_transpose(img)  # bake the orientation in before the EXIF is dropped
    if fmt == "JPEG":
        img.save(out, "JPEG", quality=92, optimize=True)
    elif fmt == "PNG":
        img.save(out, "PNG", optimize=True)
    else:
        img.save(out, "WEBP", quality=92)
    return Cleaned(out.getvalue(), ext, mime, img.width, img.height)


def _webp(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "WEBP", quality=82, method=4)
    return out.getvalue()


def render_variants(raw: bytes) -> dict[str, bytes]:
    """name -> WEBP bytes: widths up to the original (never upscaled) plus the OG cover crop."""
    img = Image.open(io.BytesIO(raw))
    img.seek(0)  # animated sources: first frame
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
    out: dict[str, bytes] = {}
    for width in VARIANT_WIDTHS:
        if width <= img.width:
            height = max(1, round(img.height * width / img.width))
            out[f"w{width}"] = _webp(img.resize((width, height), Image.LANCZOS))
    out["og"] = _webp(ImageOps.fit(img, OG_SIZE, Image.LANCZOS))
    return out
