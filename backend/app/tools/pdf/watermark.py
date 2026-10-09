from pathlib import Path

import pymupdf
from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.pdf._common import open_pdf, selected_pages

GREY = (0.5, 0.5, 0.5)


class WatermarkParams(BaseModel):
    text: str = Field("CONFIDENTIAL", min_length=1, max_length=80, description="Watermark text")
    size: int = Field(60, ge=8, le=300, description="Font size in points")
    opacity: float = Field(0.25, ge=0.05, le=1.0, description="0.05 = faint, 1 = solid")
    angle: int = Field(45, ge=-90, le=90, description="Counter-clockwise tilt in degrees")
    pages: str = Field("", description="Pages to stamp, e.g. 1-3,5. Empty = every page.")


class WatermarkPdf(Tool):
    id = "pdf.watermark"
    name = "Add text watermark"
    category = "pdf"
    description = "Stamp a tilted, semi-transparent text across the middle of each page."
    accepts = ["application/pdf"]
    batch = True
    Params = WatermarkParams

    def run(self, files: list[Path], params: WatermarkParams, ctx: ToolContext):
        src = files[0]
        total = len(open_pdf(src).pages)
        indexes = selected_pages(params.pages, total)
        length = pymupdf.get_text_length(params.text, fontname="helv", fontsize=params.size)
        out = ctx.out_unique(f"{src.stem}-watermarked.pdf")

        try:
            doc = pymupdf.open(src)
        except Exception:
            raise ToolError(f"'{src.name}' could not be opened.") from None
        with doc:
            for n, i in enumerate(indexes, start=1):
                ctx.check_cancelled()
                page = doc[i]
                centre = pymupdf.Point(page.rect.width / 2, page.rect.height / 2)
                start = pymupdf.Point(centre.x - length / 2, centre.y + params.size / 3)
                page.insert_text(
                    start,
                    params.text,
                    fontname="helv",
                    fontsize=params.size,
                    color=GREY,
                    fill_opacity=params.opacity,
                    morph=(centre, pymupdf.Matrix(params.angle)),
                    overlay=True,
                )
                ctx.progress(n / len(indexes), f"Stamped page {i + 1}")
            doc.save(out, garbage=3, deflate=True)
        return [out]
