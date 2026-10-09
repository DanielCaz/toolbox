import pytest
from pypdf import PdfReader, PdfWriter

from app.core.errors import ToolError
from app.tools.pdf._common import parse_ranges
from app.tools.pdf.merge import MergePdf
from app.tools.pdf.split import SplitPdf


def _pages(path) -> int:
    return len(PdfReader(path).pages)


def test_parse_ranges():
    assert parse_ranges("1-2,4", 5) == [[0, 1], [3]]
    assert parse_ranges("3-", 5) == [[2, 3, 4]]
    with pytest.raises(ToolError):
        parse_ranges("1-9", 5)
    with pytest.raises(ToolError):
        parse_ranges("a-b", 5)
    with pytest.raises(ToolError):
        parse_ranges(" , ", 5)


def test_merge_keeps_order_and_page_count(make_pdf, run_tool):
    a, b = make_pdf("a.pdf", 2), make_pdf("b.pdf", 3)
    (out,) = run_tool(MergePdf, [a, b], output_name="both")
    assert out.name == "both.pdf"  # extension added
    reader = PdfReader(out)
    assert len(reader.pages) == 5
    assert "of a" in reader.pages[0].extract_text()
    assert "of b" in reader.pages[2].extract_text()


def test_merge_rejects_encrypted(make_pdf, run_tool, tmp_path):
    plain = make_pdf("plain.pdf", 1)
    writer = PdfWriter(clone_from=plain)
    writer.encrypt("secret")
    locked = tmp_path / "inputs" / "locked.pdf"
    with locked.open("wb") as fh:
        writer.write(fh)
    with pytest.raises(ToolError, match="password"):
        run_tool(MergePdf, [plain, locked])


def test_merge_rejects_corrupt(make_pdf, run_tool, tmp_path):
    good = make_pdf("good.pdf", 1)
    bad = tmp_path / "inputs" / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 this is not really a pdf")
    with pytest.raises(ToolError):
        run_tool(MergePdf, [good, bad])


def test_split_ranges(make_pdf, run_tool):
    src = make_pdf("book.pdf", 6)
    outs = run_tool(SplitPdf, [src], mode="ranges", ranges="1-2,4,6-")
    assert [_pages(o) for o in outs] == [2, 1, 1]
    assert outs[0].name == "book-part-01.pdf"


def test_split_every_n(make_pdf, run_tool):
    src = make_pdf("book.pdf", 5)
    outs = run_tool(SplitPdf, [src], mode="every_n", every_n=2)
    assert [_pages(o) for o in outs] == [2, 2, 1]


def test_split_each_page(make_pdf, run_tool):
    src = make_pdf("book.pdf", 3)
    outs = run_tool(SplitPdf, [src], mode="each_page")
    assert len(outs) == 3 and all(_pages(o) == 1 for o in outs)


def test_split_out_of_range_is_a_tool_error(make_pdf, run_tool):
    src = make_pdf("book.pdf", 3)
    with pytest.raises(ToolError, match="outside the document"):
        run_tool(SplitPdf, [src], mode="ranges", ranges="2-10")
