import shutil
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, Field

from app.core.tool import Tool, ToolContext
from app.tools.image._common import open_image, output_format, save_image


class CompressImageParams(BaseModel):
    quality: int = Field(75, ge=1, le=100, description="JPG / WebP quality (lower = smaller)")
    max_side: int = Field(
        0,
        ge=0,
        le=20000,
        description="Shrink so the longest side is at most this many pixels (0 = keep)",
    )
    png_colors: int = Field(
        256,
        ge=0,
        le=256,
        description="PNG only: reduce to this many colours for a much smaller file "
        "(0 = lossless, no colour reduction)",
    )


class CompressImage(Tool):
    id = "image.compress"
    name = "Compress images"
    category = "image"
    description = "Make images smaller. If a file cannot get smaller it is returned unchanged."
    accepts = ["image/*"]
    batch = True
    Params = CompressImageParams

    def run(self, files: list[Path], params: CompressImageParams, ctx: ToolContext):
        src = files[0]
        im, fmt = open_image(src)
        pil_format, ext = output_format(fmt)

        if params.max_side and max(im.size) > params.max_side:
            im.thumbnail((params.max_side, params.max_side), Image.Resampling.LANCZOS)

        if pil_format == "PNG" and params.png_colors:
            base = im.convert("RGBA") if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
            method = Image.Quantize.FASTOCTREE if base.mode == "RGBA" else Image.Quantize.MEDIANCUT
            im = base.quantize(colors=params.png_colors, method=method)

        out = ctx.out_unique(f"{src.stem}-small.{ext}")
        save_image(im, out, pil_format, params.quality)

        before, after = src.stat().st_size, out.stat().st_size
        if after >= before:
            out.unlink()  # free the name first, then hand back the untouched original bytes
            out = ctx.out_unique(f"{src.stem}-small{src.suffix}")
            shutil.copyfile(src, out)
            ctx.progress(1.0, "Already as small as it gets; kept the original")
        else:
            ctx.progress(1.0, f"{before / 1024:.0f} KB → {after / 1024:.0f} KB")
        return [out]
