"""Helpers shared by the PDF tools (underscore prefix = not a tool)."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.core.errors import ToolError


def open_pdf(path: Path) -> PdfReader:
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ToolError(f"'{path.name}' is password protected. Unlock it first.")
        len(reader.pages)  # force a parse so corrupt files fail here
        return reader
    except ToolError:
        raise
    except (PyPdfError, ValueError, OSError, KeyError):
        raise ToolError(
            f"'{path.name}' could not be read as a PDF (corrupt or unsupported)."
        ) from None


def parse_ranges(spec: str, total: int) -> list[list[int]]:
    """Parse '1-3,5,7-' into zero-based page lists, one list per comma-separated part."""
    groups: list[list[int]] = []
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        try:
            if "-" in part:
                a, _, b = part.partition("-")
                start = int(a) if a.strip() else 1
                end = int(b) if b.strip() else total
            else:
                start = end = int(part)
        except ValueError:
            raise ToolError(f"Invalid page range '{part}'. Use something like 1-3,5,7-.") from None
        if start < 1 or end < start or end > total:
            raise ToolError(f"Range '{part}' is outside the document (it has {total} pages).")
        groups.append(list(range(start - 1, end)))
    if not groups:
        raise ToolError("No page ranges given.")
    return groups


def selected_pages(spec: str, total: int) -> list[int]:
    """Zero-based page indexes for a spec; an empty spec means every page."""
    if not spec.strip():
        return list(range(total))
    return [i for group in parse_ranges(spec, total) for i in group]


def page_count(path: Path) -> int:
    return len(open_pdf(path).pages)
