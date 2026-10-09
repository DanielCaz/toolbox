from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pypdf import PdfWriter

from app.core.tool import Tool, ToolContext
from app.tools.pdf._common import open_pdf, selected_pages


class RotateParams(BaseModel):
    degrees: Literal[90, 180, 270] = Field(90, description="Clockwise rotation")
    pages: str = Field(
        "",
        description="Pages to rotate, e.g. 1-3,5. Leave empty to rotate every page.",
    )


class RotatePdf(Tool):
    id = "pdf.rotate"
    name = "Rotate PDF"
    category = "pdf"
    description = "Rotate all pages, or just some of them."
    accepts = ["application/pdf"]
    batch = True
    Params = RotateParams

    def run(self, files: list[Path], params: RotateParams, ctx: ToolContext):
        src = files[0]
        reader = open_pdf(src)
        chosen = set(selected_pages(params.pages, len(reader.pages)))
        writer = PdfWriter()
        for i, page in enumerate(reader.pages):
            writer.add_page(page.rotate(params.degrees) if i in chosen else page)
        out = ctx.out_unique(f"{src.stem}-rotated.pdf")
        with out.open("wb") as fh:
            writer.write(fh)
        return [out]
