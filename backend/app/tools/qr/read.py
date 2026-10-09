from pathlib import Path

import zxingcpp
from pydantic import BaseModel

from app.core.errors import ToolError
from app.core.tool import NoParams, Tool, ToolContext
from app.tools.image._common import open_image


class ReadQr(Tool):
    id = "qr.read"
    name = "Read QR codes & barcodes"
    category = "qr"
    description = "Decode QR codes and common barcodes (EAN, Code 128, Data Matrix...) from images."
    accepts = ["image/*"]
    max_files = None
    output = "text"
    Params = NoParams

    def run(self, files: list[Path], params: BaseModel, ctx: ToolContext):
        sections: list[str] = []
        total = 0
        for i, f in enumerate(files, start=1):
            ctx.check_cancelled()
            im, _ = open_image(f)
            found = zxingcpp.read_barcodes(im.convert("RGB"))
            lines = [f"[{b.format.name}] {b.text}" for b in found]
            total += len(lines)
            sections.append("\n".join(lines) if lines else "(nothing found)")
            ctx.progress(i / len(files), f"Scanned {f.name}")

        if total == 0:
            raise ToolError(
                "No QR code or barcode found. Try a sharper, larger or better-lit picture."
            )
        if len(files) == 1:
            return sections[0]
        return "\n\n".join(f"=== {f.name} ===\n{s}" for f, s in zip(files, sections, strict=True))
