from pathlib import Path
from typing import Literal

import pymupdf
from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.pdf._common import open_pdf, selected_pages

MAX_PIXELS = 100_000_000  # per page; guards against a 600 dpi poster eating all RAM


class ToImagesParams(BaseModel):
    format: Literal["png", "jpg"] = Field("png", description="Image format")
    dpi: int = Field(150, ge=36, le=600, description="Resolution (150 is fine for screens)")
    pages: str = Field("", description="Pages to render, e.g. 1-3,5. Empty = every page.")


class PdfToImages(Tool):
    id = "pdf.to_images"
    name = "PDF to images"
    category = "pdf"
    description = "Render PDF pages as PNG or JPG images."
    accepts = ["application/pdf"]
    batch = True
    slow = True
    Params = ToImagesParams

    def run(self, files: list[Path], params: ToImagesParams, ctx: ToolContext):
        src = files[0]
        total = len(open_pdf(src).pages)
        indexes = selected_pages(params.pages, total)
        width = max(2, len(str(total)))
        scale = params.dpi / 72
        outputs: list[Path] = []

        try:
            doc = pymupdf.open(src)
        except Exception:
            raise ToolError(f"'{src.name}' could not be opened for rendering.") from None
        with doc:
            for n, i in enumerate(indexes, start=1):
                ctx.check_cancelled()
                page = doc[i]
                rect = page.rect
                if rect.width * scale * rect.height * scale > MAX_PIXELS:
                    raise ToolError(
                        f"Page {i + 1} is too large to render at {params.dpi} dpi. Lower the dpi."
                    )
                pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                out = ctx.out_unique(f"{src.stem}-p{i + 1:0{width}d}.{params.format}")
                pix.save(out, jpg_quality=90) if params.format == "jpg" else pix.save(out)
                outputs.append(out)
                ctx.progress(n / len(indexes), f"Rendered page {i + 1}")
        return outputs
