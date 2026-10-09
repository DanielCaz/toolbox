from pathlib import Path
from typing import Literal

from PIL import Image
from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.image._common import open_image

PNG_SIZES = [16, 32, 48, 64, 128, 192, 256, 512]
ICO_SIZES = [16, 32, 48]

SNIPPET = """<!-- Put the files in your site root, then add this to <head> -->
<link rel="icon" href="/favicon.ico" sizes="48x48">
<link rel="icon" type="image/png" sizes="32x32" href="/icon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/icon-16.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<!-- Web app manifest icons: /icon-192.png and /icon-512.png -->
"""


class FaviconParams(BaseModel):
    fit: Literal["crop", "pad"] = Field(
        "crop",
        description="Non-square images: crop to the centre square, or pad with transparency",
    )


class Favicon(Tool):
    id = "image.favicon"
    name = "Favicon & app icon set"
    category = "image"
    description = (
        "Make favicon.ico, PNG icons, an Apple touch icon and an HTML snippet from one image."
    )
    accepts = ["image/*"]
    batch = True
    Params = FaviconParams

    def run(self, files: list[Path], params: FaviconParams, ctx: ToolContext):
        src = files[0]
        im, _ = open_image(src)
        im = im.convert("RGBA")
        w, h = im.size
        if min(w, h) < 64:
            raise ToolError(f"The image is only {w}×{h}. Use one that is at least 64×64.")

        side = min(w, h) if params.fit == "crop" else max(w, h)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        if params.fit == "crop":
            left, top = (w - side) // 2, (h - side) // 2
            square = im.crop((left, top, left + side, top + side))
        else:
            square.paste(im, ((side - w) // 2, (side - h) // 2))

        outputs: list[Path] = []
        for n, size in enumerate(PNG_SIZES, start=1):
            out = ctx.out_unique(f"icon-{size}.png")
            square.resize((size, size), Image.Resampling.LANCZOS).save(out, optimize=True)
            outputs.append(out)
            ctx.progress(n / (len(PNG_SIZES) + 2), f"{size}×{size}")

        apple = ctx.out_unique("apple-touch-icon.png")
        flat = Image.new("RGB", (180, 180), "white")  # iOS ignores transparency
        scaled = square.resize((180, 180), Image.Resampling.LANCZOS)
        flat.paste(scaled, mask=scaled.getchannel("A"))
        flat.save(apple, optimize=True)
        outputs.append(apple)

        ico = ctx.out_unique("favicon.ico")
        square.resize((256, 256), Image.Resampling.LANCZOS).save(
            ico, format="ICO", sizes=[(s, s) for s in ICO_SIZES]
        )
        outputs.append(ico)

        snippet = ctx.out_unique("head-snippet.html")
        snippet.write_text(SNIPPET, encoding="utf-8")
        outputs.append(snippet)
        return outputs
