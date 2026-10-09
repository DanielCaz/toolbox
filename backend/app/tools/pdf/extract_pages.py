from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pypdf import PdfWriter

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.pdf._common import open_pdf, selected_pages


class ExtractPagesParams(BaseModel):
    pages: str = Field(
        "1",
        description="Page list such as 1-3,5,7-. In 'keep' mode the order you type is the "
        "output order, so 3,1,2 reorders and 1,1 duplicates.",
    )
    mode: Literal["keep", "delete"] = Field(
        "keep", description="keep: output only these pages · delete: output everything else"
    )


class ExtractPages(Tool):
    id = "pdf.extract_pages"
    name = "Extract, delete or reorder pages"
    category = "pdf"
    description = "Keep selected pages (in the order given) or remove them."
    accepts = ["application/pdf"]
    batch = True
    Params = ExtractPagesParams

    def run(self, files: list[Path], params: ExtractPagesParams, ctx: ToolContext):
        src = files[0]
        reader = open_pdf(src)
        total = len(reader.pages)
        picked = selected_pages(params.pages, total) if params.pages.strip() else []
        if params.mode == "delete":
            drop = set(picked)
            picked = [i for i in range(total) if i not in drop]
        if not picked:
            raise ToolError("That would leave the PDF with no pages.")

        writer = PdfWriter()
        for i in picked:
            writer.add_page(reader.pages[i])
        out = ctx.out_unique(f"{src.stem}-pages.pdf")
        with out.open("wb") as fh:
            writer.write(fh)
        return [out]
