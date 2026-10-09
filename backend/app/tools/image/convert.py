from pathlib import Path
from typing import Literal

import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext

pillow_heif.register_heif_opener()  # HEIC/HEIF input support
Image.MAX_IMAGE_PIXELS = 200_000_000  # decompression-bomb guard (errors at 2x)

# user-facing format -> (Pillow format name, file extension)
FORMATS = {
    "png": ("PNG", "png"),
    "jpg": ("JPEG", "jpg"),
    "webp": ("WEBP", "webp"),
    "gif": ("GIF", "gif"),
    "bmp": ("BMP", "bmp"),
    "tiff": ("TIFF", "tiff"),
    "ico": ("ICO", "ico"),
}
NO_ALPHA = {"JPEG", "BMP"}


class ConvertParams(BaseModel):
    format: Literal["png", "jpg", "webp", "gif", "bmp", "tiff", "ico"] = Field(
        "png", description="Target format"
    )
    quality: int = Field(
        90, ge=1, le=100, description="Quality for JPG and WebP (ignored by other formats)"
    )


def _flatten_alpha(im: Image.Image) -> Image.Image:
    """Composite transparency onto white (needed for JPEG/BMP)."""
    rgba = im.convert("RGBA")
    background = Image.new("RGB", rgba.size, (255, 255, 255))
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background


class ConvertImage(Tool):
    id = "image.convert"
    name = "Convert images"
    category = "image"
    description = "Convert images between PNG, JPG, WebP, GIF, BMP, TIFF and ICO. Reads HEIC too."
    accepts = ["image/*"]
    max_files = None
    Params = ConvertParams

    def run(self, files: list[Path], params: ConvertParams, ctx: ToolContext):
        pil_format, ext = FORMATS[params.format]
        outputs: list[Path] = []

        for i, f in enumerate(files, start=1):
            try:
                with Image.open(f) as im:
                    im.load()
                    im = ImageOps.exif_transpose(im)

                    if pil_format in NO_ALPHA and (
                        im.mode in ("RGBA", "LA") or "transparency" in im.info
                    ):
                        im = _flatten_alpha(im)
                    elif im.mode == "CMYK" or (pil_format in NO_ALPHA and im.mode != "RGB"):
                        im = im.convert("RGB")
                    elif im.mode == "P" and pil_format != "GIF":
                        im = im.convert("RGBA")

                    save_kwargs: dict = {}
                    if pil_format == "JPEG":
                        save_kwargs = {"quality": params.quality, "optimize": True}
                    elif pil_format == "WEBP":
                        save_kwargs = {"quality": params.quality}
                    elif pil_format == "PNG":
                        save_kwargs = {"optimize": True}
                    elif pil_format == "ICO":
                        im.thumbnail((256, 256))
                        save_kwargs = {"sizes": [im.size]}

                    out = ctx.out_unique(f"{f.stem}.{ext}")
                    im.save(out, format=pil_format, **save_kwargs)
                    outputs.append(out)
            except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
                raise ToolError(f"'{f.name}' could not be read or converted as an image.") from None
            ctx.progress(i / len(files), f"Converted {f.name}")
        return outputs
