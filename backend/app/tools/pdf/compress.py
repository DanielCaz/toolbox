import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.pdf._common import open_pdf

PRESETS = {"screen": "/screen", "ebook": "/ebook", "printer": "/printer"}


class CompressParams(BaseModel):
    quality: Literal["screen", "ebook", "printer"] = Field(
        "ebook",
        description="screen: smallest (72 dpi images) · ebook: good for reading (150 dpi) · "
        "printer: high quality (300 dpi)",
    )


class CompressPdf(Tool):
    id = "pdf.compress"
    name = "Compress PDF"
    category = "pdf"
    description = "Shrink a PDF by downsampling its images (Ghostscript)."
    accepts = ["application/pdf"]
    batch = True
    slow = True
    requires = ["gs"]
    Params = CompressParams

    def run(self, files: list[Path], params: CompressParams, ctx: ToolContext):
        src = files[0]
        open_pdf(src)  # friendly errors for corrupt / encrypted input
        out = ctx.out_unique(f"{src.stem}-compressed.pdf")
        ctx.progress(0.1, "Compressing")
        ctx.run_cmd(
            [
                "gs",
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.5",
                f"-dPDFSETTINGS={PRESETS[params.quality]}",
                "-dNOPAUSE",
                "-dQUIET",
                "-dBATCH",
                "-dSAFER",
                f"-sOutputFile={out}",
                str(src),
            ],
            timeout=600,
        )
        if not out.exists() or out.stat().st_size == 0:
            raise ToolError("Ghostscript produced no output.")
        before, after = src.stat().st_size, out.stat().st_size
        if after >= before:  # nothing to gain: hand back the original bytes untouched
            shutil.copyfile(src, out)
            ctx.progress(1.0, "Already as small as it gets; kept the original")
        else:
            ctx.progress(1.0, f"{before / 1024:.0f} KB → {after / 1024:.0f} KB")
        return [out]
