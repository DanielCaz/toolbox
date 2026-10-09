from pathlib import Path
from typing import Literal

from PIL import Image
from pydantic import BaseModel, Field

from app.core.tool import Tool, ToolContext
from app.tools.image._common import flatten_alpha, open_image

DPI = 150
# page sizes in pixels at 150 dpi
PAGES = {"a4": (1240, 1754), "letter": (1275, 1650)}


class ImagesToPdfParams(BaseModel):
    page_size: Literal["fit", "a4", "letter"] = Field(
        "fit",
        description="fit: each page is exactly the size of its image · a4 / letter: image "
        "centred on a white page",
    )
    margin: int = Field(40, ge=0, le=300, description="White border in pixels (a4 / letter only)")
    output_name: str = Field("images.pdf", max_length=100, description="Name of the PDF")


class ImagesToPdf(Tool):
    id = "image.to_pdf"
    name = "Images to PDF"
    category = "image"
    description = "Combine images into one PDF, one image per page, in the order given."
    accepts = ["image/*"]
    max_files = None
    Params = ImagesToPdfParams

    def run(self, files: list[Path], params: ImagesToPdfParams, ctx: ToolContext):
        pages: list[Image.Image] = []
        for i, f in enumerate(files, start=1):
            ctx.check_cancelled()
            im, _ = open_image(f)
            im = flatten_alpha(im) if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
            if params.page_size != "fit":
                pw, ph = PAGES[params.page_size]
                if im.width > im.height:  # landscape pictures get landscape pages
                    pw, ph = ph, pw
                box = (max(1, pw - 2 * params.margin), max(1, ph - 2 * params.margin))
                im.thumbnail(box, Image.Resampling.LANCZOS)
                page = Image.new("RGB", (pw, ph), "white")
                page.paste(im, ((pw - im.width) // 2, (ph - im.height) // 2))
                im = page
            pages.append(im)
            ctx.progress(i / len(files), f"Prepared {f.name}")

        name = Path(params.output_name.strip() or "images.pdf").name
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        out = ctx.out_unique(name)
        pages[0].save(out, "PDF", save_all=True, append_images=pages[1:], resolution=DPI)
        return [out]
