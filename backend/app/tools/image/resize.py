from pathlib import Path
from typing import Literal

from PIL import Image
from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.image._common import open_image, output_format, save_image

MAX_SIDE = 20000


class ResizeParams(BaseModel):
    mode: Literal["width", "height", "percent", "fit_box", "exact"] = Field(
        "width",
        description="width / height: set one side and keep the proportions · percent: scale · "
        "fit_box: shrink to fit inside width × height · exact: stretch to width × height",
    )
    width: int = Field(1280, ge=1, le=MAX_SIDE, description="Pixels (width, fit_box, exact)")
    height: int = Field(720, ge=1, le=MAX_SIDE, description="Pixels (height, fit_box, exact)")
    percent: float = Field(50, ge=1, le=800, description="Scale in % (percent mode)")
    allow_upscale: bool = Field(True, description="Allow making the image larger than the original")
    quality: int = Field(90, ge=1, le=100, description="JPG / WebP quality")


def target_size(w: int, h: int, p: ResizeParams) -> tuple[int, int]:
    if p.mode == "width":
        return p.width, max(1, round(h * p.width / w))
    if p.mode == "height":
        return max(1, round(w * p.height / h)), p.height
    if p.mode == "percent":
        return max(1, round(w * p.percent / 100)), max(1, round(h * p.percent / 100))
    if p.mode == "fit_box":
        ratio = min(p.width / w, p.height / h)
        return max(1, round(w * ratio)), max(1, round(h * ratio))
    return p.width, p.height


class ResizeImage(Tool):
    id = "image.resize"
    name = "Resize images"
    category = "image"
    description = "Scale images by width, height, percentage or to fit a box."
    accepts = ["image/*"]
    batch = True
    Params = ResizeParams

    def run(self, files: list[Path], params: ResizeParams, ctx: ToolContext):
        src = files[0]
        im, fmt = open_image(src)
        w, h = im.size
        new_w, new_h = target_size(w, h, params)
        if not params.allow_upscale and (new_w > w or new_h > h):
            new_w, new_h = min(new_w, w), min(new_h, h)
            if params.mode != "exact":
                new_w, new_h = w, h
        if new_w * new_h > 200_000_000 or max(new_w, new_h) > MAX_SIDE:
            raise ToolError(f"The result ({new_w}×{new_h}) would be too large.")

        resized = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
        pil_format, ext = output_format(fmt)
        out = ctx.out_unique(f"{src.stem}-{new_w}x{new_h}.{ext}")
        save_image(resized, out, pil_format, params.quality)
        ctx.progress(1.0, f"{w}×{h} → {new_w}×{new_h}")
        return [out]
