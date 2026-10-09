from pathlib import Path

import pymupdf
from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.pdf._common import open_pdf, selected_pages


class ExtractTextParams(BaseModel):
    pages: str = Field("", description="Pages to read, e.g. 1-3,5. Empty = every page.")
    page_markers: bool = Field(True, description="Insert a '--- Page N ---' line between pages")


class ExtractText(Tool):
    id = "pdf.extract_text"
    name = "Extract text from PDF"
    category = "pdf"
    description = "Pull the text layer out of a PDF. For scans, run 'OCR a PDF' first."
    accepts = ["application/pdf"]
    batch = True
    output = "text"
    Params = ExtractTextParams

    def run(self, files: list[Path], params: ExtractTextParams, ctx: ToolContext):
        src = files[0]
        total = len(open_pdf(src).pages)
        indexes = selected_pages(params.pages, total)
        chunks: list[str] = []
        found_text = False
        try:
            doc = pymupdf.open(src)
        except Exception:
            raise ToolError(f"'{src.name}' could not be opened.") from None
        with doc:
            for n, i in enumerate(indexes, start=1):
                ctx.check_cancelled()
                text = doc[i].get_text("text").strip()
                found_text = found_text or bool(text)
                chunks.append(f"--- Page {i + 1} ---\n{text}" if params.page_markers else text)
                ctx.progress(n / len(indexes), f"Read page {i + 1}")

        if not found_text:
            raise ToolError(
                "No text layer found. This looks like a scan: run 'OCR a PDF' first, "
                "or use 'Image to text' on its pages."
            )
        return "\n\n".join(chunks)
