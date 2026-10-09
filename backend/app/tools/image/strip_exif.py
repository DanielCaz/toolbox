from pathlib import Path

from pydantic import BaseModel, Field

from app.core.tool import Tool, ToolContext
from app.tools.image._common import open_image, output_format, save_image


class StripExifParams(BaseModel):
    jpeg_quality: int = Field(
        95, ge=60, le=100, description="Quality used when a JPG has to be re-saved"
    )


class StripExif(Tool):
    id = "image.strip_exif"
    name = "Remove photo metadata"
    category = "image"
    description = "Delete EXIF data (GPS location, camera, date) from photos before sharing them."
    accepts = ["image/*"]
    batch = True
    Params = StripExifParams

    def run(self, files: list[Path], params: StripExifParams, ctx: ToolContext):
        src = files[0]
        # open_image applies the EXIF orientation first, so the picture stays upright even
        # though the orientation tag is dropped. The re-save writes pixels only, no metadata.
        im, fmt = open_image(src)
        pil_format, ext = output_format(fmt)
        out = ctx.out_unique(f"{src.stem}-clean.{ext}")
        save_image(im, out, pil_format, params.jpeg_quality)
        return [out]
