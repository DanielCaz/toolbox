from pathlib import Path
from typing import Literal

import pymupdf
from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.pdf._common import open_pdf


class PageNumberParams(BaseModel):
    position: Literal["bottom_center", "bottom_right", "bottom_left", "top_center", "top_right"] = (
        Field("bottom_center", description="Where the number goes")
    )
    format: Literal["n", "n_of_total", "page_n"] = Field(
        "n", description="n → 3 · n_of_total → 3 / 12 · page_n → Page 3"
    )
    start: int = Field(1, ge=0, le=100000, description="Number given to the first page")
    size: int = Field(10, ge=6, le=48, description="Font size in points")
    margin: int = Field(28, ge=8, le=120, description="Distance from the page edge in points")


class PageNumbers(Tool):
    id = "pdf.page_numbers"
    name = "Add page numbers"
    category = "pdf"
    description = "Stamp page numbers on every page."
    accepts = ["application/pdf"]
    batch = True
    Params = PageNumberParams

    def run(self, files: list[Path], params: PageNumberParams, ctx: ToolContext):
        src = files[0]
        open_pdf(src)
        out = ctx.out_unique(f"{src.stem}-numbered.pdf")
        try:
            doc = pymupdf.open(src)
        except Exception:
            raise ToolError(f"'{src.name}' could not be opened.") from None
        with doc:
            total = doc.page_count
            for i in range(total):
                ctx.check_cancelled()
                number = params.start + i
                label = {
                    "n": f"{number}",
                    "n_of_total": f"{number} / {params.start + total - 1}",
                    "page_n": f"Page {number}",
                }[params.format]
                page = doc[i]
                width = pymupdf.get_text_length(label, fontname="helv", fontsize=params.size)
                w, h = page.rect.width, page.rect.height
                where, side = params.position.split("_")
                x = {
                    "left": params.margin,
                    "center": (w - width) / 2,
                    "right": w - params.margin - width,
                }[side]
                y = h - params.margin if where == "bottom" else params.margin + params.size
                page.insert_text(
                    (x, y), label, fontname="helv", fontsize=params.size, color=(0, 0, 0)
                )
                ctx.progress((i + 1) / total, f"Numbered page {i + 1}")
            doc.save(out, garbage=3, deflate=True)
        return [out]
