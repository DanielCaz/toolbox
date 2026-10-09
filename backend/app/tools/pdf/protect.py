from pathlib import Path

from pydantic import BaseModel, Field
from pypdf import PdfWriter

from app.core.tool import Tool, ToolContext
from app.tools.pdf._common import open_pdf


class ProtectParams(BaseModel):
    password: str = Field(
        ..., min_length=1, max_length=128, description="Password needed to open the PDF"
    )


class ProtectPdf(Tool):
    id = "pdf.protect"
    name = "Password-protect PDF"
    category = "pdf"
    description = (
        "Encrypt a PDF with a password (AES-256). Keep the password: it cannot be recovered."
    )
    accepts = ["application/pdf"]
    batch = True
    Params = ProtectParams

    def run(self, files: list[Path], params: ProtectParams, ctx: ToolContext):
        src = files[0]
        reader = open_pdf(src)
        writer = PdfWriter(clone_from=reader)
        writer.encrypt(params.password, algorithm="AES-256")
        out = ctx.out_unique(f"{src.stem}-protected.pdf")
        with out.open("wb") as fh:
            writer.write(fh)
        return [out]
