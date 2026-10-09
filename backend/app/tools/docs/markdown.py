import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.files import sniff_mime
from app.core.tool import Tool, ToolContext
from app.tools.docs._common import soffice_convert

FROM_BY_EXT = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "markdown",
    ".html": "html",
    ".htm": "html",
    ".docx": "docx",
    ".odt": "odt",
    ".epub": "epub",
    ".rst": "rst",
    ".tex": "latex",
    ".latex": "latex",
}
# target -> (pandoc writer, extension)
TARGETS = {
    "html": ("html", "html"),
    "docx": ("docx", "docx"),
    "odt": ("odt", "odt"),
    "epub": ("epub", "epub"),
    "markdown": ("gfm", "md"),
    "plain": ("plain", "txt"),
    "rst": ("rst", "rst"),
    "latex": ("latex", "tex"),
    "pdf": ("html", "pdf"),  # pandoc → standalone HTML → LibreOffice → PDF (no LaTeX needed)
}


# Metadata keys that are safe to pass on. Everything else is dropped because several keys make
# Pandoc read files from disk (epub-cover-image, epub-metadata, css, reference-doc, ...).
SAFE_META = {"title", "subtitle", "author", "date", "abstract", "lang", "keywords", "description"}
# Writers that work with `pandoc --sandbox` on distro builds (the others read templates from disk).
SANDBOX_OK = {"gfm", "plain", "rst", "latex"}


def scrub_ast(node: Any) -> Any:
    """Make a Pandoc JSON AST safe to write out.

    Images that are not inline ``data:`` URIs are replaced by their alt text, so a document can
    never make Pandoc embed or fetch another file (``![](/etc/passwd)``, ``<img src=http://...>``).
    """
    if isinstance(node, list):
        out: list[Any] = []
        for item in node:
            if isinstance(item, dict) and item.get("t") == "Image":
                src = item["c"][2][0]
                if isinstance(src, str) and src.startswith("data:"):
                    out.append(scrub_ast(item))
                else:
                    out.extend(scrub_ast(item["c"][1]))  # the alt text, as plain inlines
            else:
                out.append(scrub_ast(item))
        return out
    if isinstance(node, dict):
        return {k: scrub_ast(v) for k, v in node.items()}
    return node


def sanitise_document(doc: dict) -> dict:
    doc = scrub_ast(doc)
    doc["meta"] = {k: v for k, v in doc.get("meta", {}).items() if k in SAFE_META}
    return doc


class MarkdownParams(BaseModel):
    to: Literal["html", "docx", "odt", "epub", "markdown", "plain", "rst", "latex", "pdf"] = Field(
        "html", description="Output format"
    )
    from_format: Literal["auto", "markdown", "html", "docx", "odt", "epub", "rst", "latex"] = Field(
        "auto", description="Input format (auto = from the file extension)"
    )
    toc: bool = Field(False, description="Add a table of contents (html, docx, odt, epub, pdf)")
    title: str = Field("", max_length=200, description="Document title (optional)")


class MarkdownConvert(Tool):
    id = "docs.markdown"
    name = "Document converter (Pandoc)"
    category = "docs"
    description = (
        "Convert between Markdown, HTML, Word, OpenDocument, EPUB, reStructuredText and PDF."
    )
    accepts = [
        "text/*",
        "application/xhtml+xml",
        "application/zip",
        "application/epub+zip",
        "application/vnd.openxmlformats-officedocument.*",
        "application/vnd.oasis.opendocument.*",
    ]
    batch = True
    requires = ["pandoc"]
    Params = MarkdownParams

    def run(self, files: list[Path], params: MarkdownParams, ctx: ToolContext):
        src = files[0]
        source = params.from_format
        if source == "auto":
            source = FROM_BY_EXT.get(src.suffix.lower())
            if source is None:
                source = "html" if sniff_mime(src) == "text/html" else "markdown"

        writer, ext = TARGETS[params.to]
        if source == params.to:
            raise ToolError("The input is already in that format.")
        title = params.title or src.stem
        out = ctx.out_unique(f"{src.stem}.{ext}")
        wants_pdf = params.to == "pdf"
        target_path = ctx.scratch("pandoc") / f"{src.stem}.html" if wants_pdf else out

        # Step 1: read the input inside Pandoc's sandbox (it may not touch any other file).
        ast_path = ctx.scratch("pandoc") / f"{src.stem}.json"
        ctx.progress(0.15, "Reading")
        ctx.run_cmd(
            ["pandoc", "--sandbox", "-f", source, "-t", "json", "-o", ast_path, src], timeout=120
        )

        # Step 2: scrub the parsed document, then write it out from the clean version.
        try:
            doc = json.loads(ast_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ToolError(f"'{src.name}' could not be parsed.") from None
        ast_path.write_text(json.dumps(sanitise_document(doc)), encoding="utf-8")

        args: list = ["pandoc"]
        if writer in SANDBOX_OK:
            args.append("--sandbox")
        args += ["-f", "json", "-t", writer, "-o", target_path, "--wrap=none"]
        args += ["--metadata", f"title={title}" if params.title else f"pagetitle={title}"]
        if writer in ("html", "docx", "odt", "epub", "latex"):
            args.append("--standalone")
        if params.toc and writer in ("html", "docx", "odt", "epub"):
            args.append("--toc")
        args.append(ast_path)

        ctx.progress(0.4, "Converting")
        ctx.run_cmd(args, timeout=180)

        if wants_pdf:
            ctx.progress(0.6, "Rendering PDF")
            produced = soffice_convert(
                ctx, target_path, "pdf:writer_web_pdf_Export", ctx.scratch("pdf-out")
            )
            produced.replace(out)
        return [out]
