import pytest
from pypdf import PdfReader

from app.core.errors import ToolError
from app.tools.ocr.ocr_image import OcrImage
from app.tools.ocr.ocr_pdf import OcrPdf
from tests.conftest import needs_ocr_pdf, needs_tesseract


@needs_tesseract
def test_ocr_image_reads_text(make_text_image, run_tool):
    text = run_tool(OcrImage, [make_text_image()], languages="eng")
    assert "TOOLBOX" in text.upper()


@needs_tesseract
def test_ocr_image_multiple_files_get_headers(make_text_image, run_tool):
    a = make_text_image("a.png", "ALPHA ONE")
    b = make_text_image("b.png", "BRAVO TWO")
    text = run_tool(OcrImage, [a, b])
    assert "=== a.png ===" in text and "=== b.png ===" in text
    assert "ALPHA" in text.upper() and "BRAVO" in text.upper()


@needs_tesseract
def test_ocr_unknown_language_is_a_tool_error(make_text_image, run_tool):
    with pytest.raises(ToolError, match="not installed"):
        run_tool(OcrImage, [make_text_image()], languages="zzz")


@needs_ocr_pdf
def test_ocr_pdf_adds_searchable_text_layer(make_scanned_pdf, run_tool):
    src = make_scanned_pdf()
    assert PdfReader(src).pages[0].extract_text().strip() == ""  # a true scan: no text yet
    (out,) = run_tool(OcrPdf, [src], languages="eng")
    assert out.name == "scan-ocr.pdf"
    assert "TOOLBOX" in PdfReader(out).pages[0].extract_text().upper()
