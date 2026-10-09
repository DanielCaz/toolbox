from pathlib import Path

import pikepdf

from app.core.errors import ToolError
from app.core.tool import NoParams, Tool, ToolContext


class StripMetadata(Tool):
    id = "pdf.strip_metadata"
    name = "Remove PDF metadata"
    category = "pdf"
    description = "Delete author, title, creator, producer and XMP data from a PDF."
    accepts = ["application/pdf"]
    batch = True
    Params = NoParams

    def run(self, files: list[Path], params: NoParams, ctx: ToolContext):
        src = files[0]
        out = ctx.out_unique(f"{src.stem}-clean.pdf")
        try:
            with pikepdf.open(src) as pdf:
                for key in list(pdf.docinfo.keys()):
                    del pdf.docinfo[key]
                if "/Metadata" in pdf.Root:
                    del pdf.Root["/Metadata"]
                pdf.save(out)
        except pikepdf.PasswordError:
            raise ToolError(f"'{src.name}' is password protected. Unlock it first.") from None
        except (pikepdf.PdfError, OSError):
            raise ToolError(f"'{src.name}' could not be read as a PDF.") from None
        return [out]
