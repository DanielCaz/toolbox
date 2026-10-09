from pathlib import Path

from app.core.tool import NoParams, Tool, ToolContext
from app.tools.docs._common import soffice_convert

OFFICE_TYPES = [
    "application/vnd.openxmlformats-officedocument.*",  # docx, xlsx, pptx
    "application/vnd.oasis.opendocument.*",  # odt, ods, odp
    "application/vnd.ms-*",  # doc, xls, ppt
    "application/msword",
    "application/rtf",
    "text/rtf",
    "text/plain",
    "text/csv",
    "text/html",
    "application/x-ole-storage",  # older libmagic names for legacy Office files
    "application/CDFV2*",
]


class OfficeToPdf(Tool):
    id = "docs.office_to_pdf"
    name = "Office to PDF"
    category = "docs"
    description = "Convert Word, Excel, PowerPoint, OpenDocument, RTF, CSV or HTML files to PDF."
    accepts = OFFICE_TYPES
    batch = True
    slow = True
    requires = ["soffice"]
    Params = NoParams

    def run(self, files: list[Path], params: NoParams, ctx: ToolContext):
        src = files[0]
        ctx.progress(0.1, f"Converting {src.name}")
        produced = soffice_convert(ctx, src, "pdf", ctx.scratch("pdf-out"))
        out = ctx.out_unique(f"{src.stem}.pdf")
        produced.replace(out)
        return [out]
