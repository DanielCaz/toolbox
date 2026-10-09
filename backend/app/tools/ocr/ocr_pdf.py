from pathlib import Path
from typing import Literal

import ocrmypdf
from ocrmypdf import exceptions as ocr_exc
from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.ocr._common import LANG_PATTERN, parse_languages


class OcrPdfParams(BaseModel):
    languages: str = Field(
        "eng",
        pattern=LANG_PATTERN,
        description="Tesseract language codes joined with + (e.g. eng+spa)",
    )
    mode: Literal["skip_text", "redo", "force"] = Field(
        "skip_text",
        description="skip_text: leave pages that already have text; "
        "redo: re-run OCR on pages that were OCRed before; "
        "force: rasterize and OCR every page",
    )
    deskew: bool = Field(False, description="Straighten slightly rotated scans")
    rotate_pages: bool = Field(
        True, description="Auto-rotate pages that are upside down or sideways"
    )


class OcrPdf(Tool):
    id = "ocr.pdf"
    name = "OCR a PDF"
    category = "ocr"
    description = "Turn a scanned PDF into a searchable PDF with a selectable text layer."
    accepts = ["application/pdf"]
    batch = True
    slow = True
    requires = ["tesseract", "gs"]
    Params = OcrPdfParams

    def run(self, files: list[Path], params: OcrPdfParams, ctx: ToolContext):
        src = files[0]
        languages = parse_languages(params.languages)
        out = ctx.out_unique(f"{src.stem}-ocr.pdf")
        ctx.progress(0.05, "Running OCR (this can take a while)")

        try:
            ocrmypdf.ocr(
                src,
                out,
                language=languages,
                skip_text=params.mode == "skip_text",
                redo_ocr=params.mode == "redo",
                force_ocr=params.mode == "force",
                deskew=params.deskew,
                rotate_pages=params.rotate_pages,
                output_type="pdf",
                optimize=0,
                progress_bar=False,
            )
        except ocr_exc.EncryptedPdfError:
            raise ToolError("The PDF is password protected. Unlock it first.") from None
        except ocr_exc.PriorOcrFoundError:
            raise ToolError("The PDF already has text. Choose 'redo' or 'force' mode.") from None
        except ocr_exc.InputFileError as e:
            raise ToolError(f"Could not read the PDF: {e}") from None
        except ocr_exc.MissingDependencyError as e:
            raise ToolError(f"A required OCR dependency is missing: {e}") from None
        except ocr_exc.ExitCodeException as e:
            raise ToolError(f"OCR failed: {e or e.__class__.__name__}") from None

        ctx.progress(1.0, "OCR complete")
        return [out]
