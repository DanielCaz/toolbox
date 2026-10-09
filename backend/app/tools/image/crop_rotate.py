from pathlib import Path
from typing import Literal

from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.image._common import open_image, output_format, save_image


class CropRotateParams(BaseModel):
    crop_left: int = Field(0, ge=0, le=20000, description="Pixels to trim from the left")
    crop_top: int = Field(0, ge=0, le=20000, description="Pixels to trim from the top")
    crop_right: int = Field(0, ge=0, le=20000, description="Pixels to trim from the right")
    crop_bottom: int = Field(0, ge=0, le=20000, description="Pixels to trim from the bottom")
    rotate: float = Field(
        0, ge=-360, le=360, description="Degrees counter-clockwise (the canvas grows to fit)"
    )
    flip: Literal["none", "horizontal", "vertical"] = Field("none", description="Mirror the image")
    quality: int = Field(90, ge=1, le=100, description="JPG / WebP quality")


class CropRotateImage(Tool):
    id = "image.crop_rotate"
    name = "Crop, rotate, flip"
    category = "image"
    description = "Trim edges, rotate by any angle, or mirror an image."
    accepts = ["image/*"]
    batch = True
    Params = CropRotateParams

    def run(self, files: list[Path], params: CropRotateParams, ctx: ToolContext):
        src = files[0]
        im, fmt = open_image(src)
        w, h = im.size

        box = (
            params.crop_left,
            params.crop_top,
            w - params.crop_right,
            h - params.crop_bottom,
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ToolError(f"Cropping would remove the whole {w}×{h} image.")
        if box != (0, 0, w, h):
            im = im.crop(box)

        if params.rotate % 360:
            has_alpha = im.mode in ("RGBA", "LA", "P")
            base = im.convert("RGBA") if has_alpha else im
            im = base.rotate(params.rotate, expand=True, resample=Image.Resampling.BICUBIC)
        if params.flip == "horizontal":
            im = ImageOps.mirror(im)
        elif params.flip == "vertical":
            im = ImageOps.flip(im)

        pil_format, ext = output_format(fmt)
        out = ctx.out_unique(f"{src.stem}-edited.{ext}")
        save_image(im, out, pil_format, params.quality)
        return [out]
