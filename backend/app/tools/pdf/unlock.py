from pathlib import Path

from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext


class UnlockParams(BaseModel):
    password: str = Field("", max_length=128, description="The PDF's password (blank if none)")


class UnlockPdf(Tool):
    id = "pdf.unlock"
    name = "Remove PDF password"
    category = "pdf"
    description = "Open a password-protected PDF with its password and save an unprotected copy."
    accepts = ["application/pdf"]
    batch = True
    Params = UnlockParams

    def run(self, files: list[Path], params: UnlockParams, ctx: ToolContext):
        src = files[0]
        try:
            reader = PdfReader(src)
            if reader.is_encrypted and not reader.decrypt(params.password):
                raise ToolError("Wrong password.")
            writer = PdfWriter(clone_from=reader)
            out = ctx.out_unique(f"{src.stem}-unlocked.pdf")
            with out.open("wb") as fh:
                writer.write(fh)
        except ToolError:
            raise
        except (PyPdfError, ValueError, OSError, KeyError):
            raise ToolError(f"'{src.name}' could not be read as a PDF.") from None
        return [out]
