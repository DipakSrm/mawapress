"""Pillow work. Everything here is CPU-bound and synchronous: callers run it in asyncio.to_thread."""

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

MAX_PIXELS = 40_000_000  # decompression-bomb guard (a 40 MP photo is ~160 MB decoded)
# Pillow format name -> (file extension, content type)
ALLOWED_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
    "GIF": ("gif", "image/gif"),
    "MPO": ("jpg", "image/jpeg"),  # multi-picture JPEG, what phones produce; only the first frame is kept
}
MAX_GIF_FRAMES = 300
MAX_GIF_PIXELS = 100_000_000  # across all frames
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
        frames = getattr(img, "n_frames", 1)
        if frames > MAX_GIF_FRAMES or frames * img.width * img.height > MAX_GIF_PIXELS:
            raise TooManyPixels
        if frames == 1:
            img.save(out, "GIF")
        else:
            # Re-saving drops comments; keep the animation and every frame's own duration.
            loop = img.info.get("loop", 0)
            decoded, durations = [], []
            for frame in ImageSequence.Iterator(img):
                durations.append(frame.info.get("duration", 100))
                decoded.append(frame.copy())
            decoded[0].save(out, "GIF", save_all=True, append_images=decoded[1:], duration=durations, loop=loop)
        return Cleaned(out.getvalue(), ext, mime, img.width, img.height)
    img = ImageOps.exif_transpose(img)  # bake the orientation in before the EXIF is dropped
    if fmt in ("JPEG", "MPO"):
        img.save(out, "JPEG", quality=92, optimize=True)  # an MPO saves as its first frame
    elif fmt == "PNG":
        img.save(out, "PNG", optimize=True)
    else:
        img.save(out, "WEBP", quality=92)
    return Cleaned(out.getvalue(), ext, mime, img.width, img.height)


def og_size(width: int, height: int) -> tuple[int, int]:
    """Largest 1200:630 crop that fits the source, never above 1200x630 (so never an upscale)."""
    ow, oh = OG_SIZE
    if width * oh <= height * ow:  # width-limited
        w = min(width, ow)
        return w, max(1, w * oh // ow)
    h = min(height, oh)
    return max(1, h * ow // oh), h


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
    out["og"] = _webp(ImageOps.fit(img, og_size(img.width, img.height), Image.LANCZOS))
    return out
