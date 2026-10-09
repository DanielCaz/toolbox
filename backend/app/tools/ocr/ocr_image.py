from pathlib import Path

import pillow_heif
import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.ocr._common import LANG_PATTERN, parse_languages

pillow_heif.register_heif_opener()


class OcrImageParams(BaseModel):
    languages: str = Field(
        "eng",
        pattern=LANG_PATTERN,
        description="Tesseract language codes joined with + (e.g. eng+spa)",
    )
    psm: int = Field(
        3,
        ge=0,
        le=13,
        description="Page segmentation mode: 3 = automatic (default), 6 = a single block, "
        "7 = a single line, 11 = sparse text",
    )


class OcrImage(Tool):
    id = "ocr.image"
    name = "Image to text (OCR)"
    category = "ocr"
    description = "Extract text from screenshots, photos and scans."
    accepts = ["image/*"]
    max_files = None
    output = "text"
    slow = True
    requires = ["tesseract"]
    Params = OcrImageParams

    def run(self, files: list[Path], params: OcrImageParams, ctx: ToolContext):
        lang = "+".join(parse_languages(params.languages))
        chunks: list[str] = []

        for i, f in enumerate(files, start=1):
            try:
                with Image.open(f) as im:
                    im.load()
                    im = ImageOps.exif_transpose(im)
                    if im.mode not in ("RGB", "L"):
                        im = im.convert("RGB")
                    text = pytesseract.image_to_string(
                        im, lang=lang, config=f"--psm {params.psm}", timeout=180
                    )
            except (UnidentifiedImageError, OSError):
                raise ToolError(f"'{f.name}' could not be read as an image.") from None
            except RuntimeError:  # pytesseract raises RuntimeError on timeout
                raise ToolError(f"OCR timed out on '{f.name}'.") from None
            except pytesseract.TesseractError as e:
                raise ToolError(f"Tesseract failed on '{f.name}': {e}") from None

            chunks.append(text.strip())
            ctx.progress(i / len(files), f"Read {f.name}")

        if len(files) == 1:
            return chunks[0]
        return "\n\n".join(f"=== {f.name} ===\n{t}" for f, t in zip(files, chunks, strict=True))
