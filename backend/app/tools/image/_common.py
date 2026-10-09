"""Helpers shared by the image tools (underscore prefix = not a tool)."""

from __future__ import annotations

from pathlib import Path

import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import ToolError

pillow_heif.register_heif_opener()  # HEIC/HEIF input support
Image.MAX_IMAGE_PIXELS = 200_000_000  # decompression-bomb guard (errors at 2x)

# PIL format name -> file extension used when we write the same format back out
EXT = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
    "GIF": "gif",
    "BMP": "bmp",
    "TIFF": "tiff",
    "ICO": "ico",
    "MPO": "jpg",  # multi-picture JPEG from phones
    "HEIF": "jpg",  # we cannot write HEIC; fall back to JPEG
    "AVIF": "jpg",
}


def open_image(path: Path) -> tuple[Image.Image, str]:
    """Open + fully load an image with EXIF rotation applied.

    Returns (image, source_format). Raises ToolError for anything unreadable.
    """
    try:
        with Image.open(path) as im:
            fmt = (im.format or "PNG").upper()
            im.load()
            upright = ImageOps.exif_transpose(im)
            return upright, fmt
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise ToolError(f"'{path.name}' could not be read as an image.") from None


def output_format(source_format: str) -> tuple[str, str]:
    """(PIL format, extension) to use when saving in 'the same format as the input'."""
    ext = EXT.get(source_format, "png")
    pil = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF", "bmp": "BMP"}.get(ext)
    return (pil, ext) if pil else ("PNG", "png")


def flatten_alpha(im: Image.Image) -> Image.Image:
    """Composite transparency onto white (JPEG/BMP cannot store alpha)."""
    rgba = im.convert("RGBA")
    background = Image.new("RGB", rgba.size, (255, 255, 255))
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background


def save_image(im: Image.Image, path: Path, pil_format: str, quality: int = 90) -> None:
    """Save with sensible per-format settings, fixing the mode when the format needs it."""
    if pil_format in ("JPEG", "BMP"):
        if im.mode in ("RGBA", "LA", "P") or "transparency" in im.info:
            im = flatten_alpha(im)
        elif im.mode != "RGB":
            im = im.convert("RGB")
    kwargs: dict = {}
    if pil_format == "JPEG":
        kwargs = {"quality": quality, "optimize": True}
    elif pil_format == "WEBP":
        kwargs = {"quality": quality}
    elif pil_format == "PNG":
        kwargs = {"optimize": True}
    im.save(path, format=pil_format, **kwargs)
