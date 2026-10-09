from pathlib import Path

from pydantic import BaseModel, Field
from pypdf import PdfWriter

from app.core.tool import Tool, ToolContext
from app.tools.pdf._common import open_pdf


class MergeParams(BaseModel):
    output_name: str = Field("merged.pdf", description="Name of the merged file", max_length=100)


class MergePdf(Tool):
    id = "pdf.merge"
    name = "Merge PDFs"
    category = "pdf"
    description = "Combine several PDFs into one, in the order given."
    accepts = ["application/pdf"]
    min_files = 2
    max_files = None
    Params = MergeParams

    def run(self, files: list[Path], params: MergeParams, ctx: ToolContext):
        writer = PdfWriter()
        for i, f in enumerate(files, start=1):
            open_pdf(f)  # friendly errors for encrypted / corrupt inputs
            writer.append(f)
            ctx.progress(i / len(files), f"Added {f.name}")
        name = params.output_name.strip() or "merged.pdf"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        out = ctx.out_unique(Path(name).name)
        with out.open("wb") as fh:
            writer.write(fh)
        return [out]
