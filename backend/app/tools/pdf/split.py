from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pypdf import PdfWriter

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.pdf._common import open_pdf, parse_ranges


class SplitParams(BaseModel):
    mode: Literal["ranges", "every_n", "each_page"] = Field(
        "ranges", description="How to cut the document"
    )
    ranges: str = Field(
        "1-3,5",
        description="Used in 'ranges' mode. Each comma-separated range becomes its own PDF "
        "(e.g. 1-3,5,7- where 7- means 'to the end').",
    )
    every_n: int = Field(
        1, ge=1, le=1000, description="Used in 'every_n' mode: pages per output file"
    )


class SplitPdf(Tool):
    id = "pdf.split"
    name = "Split PDF"
    category = "pdf"
    description = "Cut a PDF by page ranges, every N pages, or into one file per page."
    accepts = ["application/pdf"]
    batch = True
    Params = SplitParams

    def run(self, files: list[Path], params: SplitParams, ctx: ToolContext):
        src = files[0]
        reader = open_pdf(src)
        total = len(reader.pages)

        if params.mode == "ranges":
            groups = parse_ranges(params.ranges, total)
        elif params.mode == "every_n":
            groups = [
                list(range(i, min(i + params.every_n, total)))
                for i in range(0, total, params.every_n)
            ]
        else:
            groups = [[i] for i in range(total)]

        if not groups:
            raise ToolError("The PDF has no pages.")

        width = max(2, len(str(len(groups))))
        outputs: list[Path] = []
        for n, pages in enumerate(groups, start=1):
            writer = PdfWriter()
            for idx in pages:
                writer.add_page(reader.pages[idx])
            out = ctx.out_unique(f"{src.stem}-part-{n:0{width}d}.pdf")
            with out.open("wb") as fh:
                writer.write(fh)
            outputs.append(out)
            ctx.progress(n / len(groups), f"Wrote part {n}/{len(groups)}")
        return outputs
