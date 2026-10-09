import shutil

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from app.core.errors import ToolError
from app.tools.pdf.compress import CompressPdf
from app.tools.pdf.extract_pages import ExtractPages
from app.tools.pdf.extract_text import ExtractText
from app.tools.pdf.page_numbers import PageNumbers
from app.tools.pdf.protect import ProtectPdf
from app.tools.pdf.rotate import RotatePdf
from app.tools.pdf.strip_metadata import StripMetadata
from app.tools.pdf.to_images import PdfToImages
from app.tools.pdf.unlock import UnlockPdf
from app.tools.pdf.watermark import WatermarkPdf


def text_of(path, page):
    return PdfReader(path).pages[page].extract_text()


def test_rotate_all_and_some(make_pdf, run_tool):
    src = make_pdf("r.pdf", 3)
    (out,) = run_tool(RotatePdf, [src], degrees=90)
    assert [p.rotation for p in PdfReader(out).pages] == [90, 90, 90]
    (out2,) = run_tool(RotatePdf, [src], degrees=180, pages="2")
    assert [p.rotation for p in PdfReader(out2).pages] == [0, 180, 0]


def test_extract_keep_reorders_and_duplicates(make_pdf, run_tool):
    src = make_pdf("book.pdf", 4)
    (out,) = run_tool(ExtractPages, [src], pages="3,1,1")
    assert len(PdfReader(out).pages) == 3
    assert [
        ("Page 3" in text_of(out, 0)),
        ("Page 1" in text_of(out, 1)),
        ("Page 1" in text_of(out, 2)),
    ] == [True] * 3


def test_extract_delete(make_pdf, run_tool):
    src = make_pdf("book.pdf", 4)
    (out,) = run_tool(ExtractPages, [src], pages="2-3", mode="delete")
    assert len(PdfReader(out).pages) == 2
    assert "Page 4" in text_of(out, 1)
    with pytest.raises(ToolError, match="no pages"):
        run_tool(ExtractPages, [src], pages="1-4", mode="delete")


def test_to_images(make_pdf, run_tool):
    src = make_pdf("deck.pdf", 3)
    outs = run_tool(PdfToImages, [src], format="png", dpi=72)
    assert [o.name for o in outs] == ["deck-p01.png", "deck-p02.png", "deck-p03.png"]
    with Image.open(outs[0]) as im:
        assert abs(im.width - 595) <= 1 and abs(im.height - 842) <= 1  # A4 at 72 dpi
    jpgs = run_tool(PdfToImages, [src], format="jpg", dpi=100, pages="2")
    assert len(jpgs) == 1 and jpgs[0].suffix == ".jpg"


def test_extract_text_and_scan_error(make_pdf, make_scanned_pdf, run_tool):
    text = run_tool(ExtractText, [make_pdf("t.pdf", 2)])
    assert "--- Page 1 ---" in text and "Page 2 of t" in text
    plain = run_tool(ExtractText, [make_pdf("t.pdf", 2)], page_markers=False)
    assert "--- Page" not in plain
    with pytest.raises(ToolError, match="OCR"):
        run_tool(ExtractText, [make_scanned_pdf()])


def test_watermark_on_selected_pages(make_pdf, run_tool):
    src = make_pdf("w.pdf", 3)
    (out,) = run_tool(WatermarkPdf, [src], text="DRAFT COPY", pages="1,3")
    assert "DRAFT COPY" in text_of(out, 0)
    assert "DRAFT COPY" not in text_of(out, 1)
    assert "DRAFT COPY" in text_of(out, 2)


def test_page_numbers(make_pdf, run_tool):
    src = make_pdf("n.pdf", 3)
    (out,) = run_tool(PageNumbers, [src], format="n_of_total", start=1)
    assert "2 / 3" in text_of(out, 1)
    (out2,) = run_tool(PageNumbers, [src], format="page_n", start=10, position="top_right")
    assert "Page 12" in text_of(out2, 2)


def test_protect_then_unlock_round_trip(make_pdf, run_tool):
    src = make_pdf("s.pdf", 2)
    (locked,) = run_tool(ProtectPdf, [src], password="s3cret")
    assert PdfReader(locked).is_encrypted
    with pytest.raises(ToolError, match="Wrong password"):
        run_tool(UnlockPdf, [locked], password="nope")
    (opened,) = run_tool(UnlockPdf, [locked], password="s3cret")
    reader = PdfReader(opened)
    assert not reader.is_encrypted and "Page 2" in reader.pages[1].extract_text()
    # protected files are rejected politely by tools that cannot open them
    with pytest.raises(ToolError, match="password"):
        run_tool(RotatePdf, [locked])


def test_strip_metadata(make_pdf, run_tool, tmp_path):
    src = make_pdf("m.pdf", 1)
    writer = PdfWriter(clone_from=src)
    writer.add_metadata({"/Author": "Jane Roe", "/Title": "Secret plans"})
    tagged = tmp_path / "inputs" / "tagged.pdf"
    with tagged.open("wb") as fh:
        writer.write(fh)
    assert PdfReader(tagged).metadata.author == "Jane Roe"

    (out,) = run_tool(StripMetadata, [tagged])
    meta = PdfReader(out).metadata
    assert not meta or (meta.author is None and meta.title is None)
    assert "Page 1" in text_of(out, 0)


@pytest.mark.skipif(shutil.which("gs") is None, reason="ghostscript missing")
def test_compress_shrinks_image_pdfs_and_keeps_tiny_ones(make_pdf, run_tool, tmp_path):
    import os

    noisy = Image.frombytes("RGB", (1800, 1800), os.urandom(1800 * 1800 * 3))
    big = tmp_path / "inputs" / "big.pdf"
    big.parent.mkdir(exist_ok=True)
    noisy.save(big, "PDF", resolution=300)  # >1.5x the 72 dpi target, so gs downsamples
    (out,) = run_tool(CompressPdf, [big], quality="screen")
    assert out.stat().st_size < big.stat().st_size * 0.8

    tiny = make_pdf("tiny.pdf", 1)
    (kept,) = run_tool(CompressPdf, [tiny])
    assert kept.read_bytes() == tiny.read_bytes()  # could not improve → original returned


def test_batch_runs_the_tool_once_per_file(make_pdf, run_execute):
    files = [make_pdf(f"d{i}.pdf", 2) for i in range(3)]
    res = run_execute(RotatePdf, files, degrees=90)
    assert sorted(p.name for p in res.outputs) == [
        "d0-rotated.pdf",
        "d1-rotated.pdf",
        "d2-rotated.pdf",
    ]


def test_batch_text_tools_get_headers_and_result_file(make_pdf, run_execute):
    res = run_execute(ExtractText, [make_pdf("one.pdf", 1), make_pdf("two.pdf", 1)])
    assert "=== one.pdf ===" in res.text and "=== two.pdf ===" in res.text
    assert [p.name for p in res.outputs] == ["result.txt"]
