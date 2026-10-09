import shutil
import subprocess

import pytest
from pypdf import PdfReader

from app.core.errors import ToolError
from app.tools.docs.markdown import MarkdownConvert
from app.tools.docs.office_to_pdf import OfficeToPdf

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc missing")
needs_soffice = pytest.mark.skipif(shutil.which("soffice") is None, reason="libreoffice missing")

MD = "# Quarterly report\n\nRevenue grew **12%**.\n\n| Region | Total |\n|---|---|\n| EU | 10 |\n"


@pytest.fixture
def md_file(tmp_path):
    p = tmp_path / "inputs" / "report.md"
    p.parent.mkdir(exist_ok=True)
    p.write_text(MD, encoding="utf-8")
    return p


@needs_pandoc
def test_markdown_to_html(md_file, run_tool):
    (out,) = run_tool(MarkdownConvert, [md_file], to="html", title="Q3")
    html = out.read_text(encoding="utf-8")
    assert out.name == "report.html"
    assert "<h1" in html and "Quarterly report" in html and "<table" in html
    assert "<title>Q3</title>" in html


@needs_pandoc
def test_markdown_docx_round_trip(md_file, run_tool):
    (docx,) = run_tool(MarkdownConvert, [md_file], to="docx", toc=True)
    assert docx.name == "report.docx" and docx.stat().st_size > 2000
    (back,) = run_tool(MarkdownConvert, [docx], to="markdown")
    text = back.read_text(encoding="utf-8")
    assert back.suffix == ".md" and "Quarterly report" in text and "Revenue grew **12%**" in text


@needs_pandoc
def test_markdown_rejects_same_format(tmp_path, run_tool):
    html = tmp_path / "x.html"
    html.write_text("<p>hi</p>")
    with pytest.raises(ToolError, match="already"):
        run_tool(MarkdownConvert, [html], to="html")


@needs_pandoc
def test_markdown_reports_pandoc_failures_as_tool_errors(tmp_path, run_tool):
    bad = tmp_path / "broken.docx"
    bad.write_bytes(b"this is not a docx")
    with pytest.raises(ToolError, match="pandoc failed"):
        run_tool(MarkdownConvert, [bad], to="html")


@needs_pandoc
@needs_soffice
def test_markdown_to_pdf_via_libreoffice(md_file, run_tool):
    (pdf,) = run_tool(MarkdownConvert, [md_file], to="pdf")
    text = PdfReader(pdf).pages[0].extract_text()
    assert pdf.name == "report.pdf" and "Quarterly report" in text and "EU" in text


@needs_pandoc
@needs_soffice
def test_office_to_pdf_converts_a_word_document(md_file, tmp_path, run_tool):
    docx = tmp_path / "inputs" / "memo.docx"
    subprocess.run(["pandoc", str(md_file), "-o", str(docx)], check=True, capture_output=True)
    (pdf,) = run_tool(OfficeToPdf, [docx])
    text = PdfReader(pdf).pages[0].extract_text()
    assert pdf.name == "memo.pdf" and "Quarterly report" in text


@needs_soffice
def test_office_to_pdf_garbage_is_a_tool_error(tmp_path, run_tool):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"PK\x03\x04 definitely not a real document")
    with pytest.raises(ToolError, match="LibreOffice"):
        run_tool(OfficeToPdf, [bad])


@needs_pandoc
def test_markdown_cannot_embed_server_files(tmp_path, run_tool):
    """A document must not be able to pull other files into the output (local file disclosure)."""
    import zipfile

    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-VALUE")
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"\x89PNG fake")
    src = tmp_path / "inputs" / "evil.md"
    src.parent.mkdir(exist_ok=True)
    src.write_text(
        f"---\ntitle: Evil\nepub-cover-image: {cover}\n---\n\nHello\n\n![alt text here]({secret})\n"
    )
    for target in ("docx", "odt", "epub", "html"):
        (out,) = run_tool(MarkdownConvert, [src], to=target)
        blob = out.read_bytes()
        if zipfile.is_zipfile(out):
            with zipfile.ZipFile(out) as z:
                names = z.namelist()
                blob = b"".join(z.read(n) for n in names)
                assert not [n for n in names if "media" in n.lower() or n.endswith(".png")], target
        assert b"TOP-SECRET-VALUE" not in blob, target
        assert b"fake" not in blob, target
        assert b"alt text here" in blob or target == "epub", target  # alt text survives as text


@needs_pandoc
def test_markdown_keeps_inline_data_images(tmp_path, run_tool):
    tiny = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )
    src = tmp_path / "inputs" / "pic.md"
    src.parent.mkdir(exist_ok=True)
    src.write_text(f"![dot]({tiny})\n")
    (out,) = run_tool(MarkdownConvert, [src], to="html")
    assert "data:image/png;base64" in out.read_text()
