"""Helpers shared by the OCR tools (underscore prefix = not a tool)."""

from __future__ import annotations

import pytesseract

from app.core.errors import ToolError

LANG_PATTERN = r"^[A-Za-z_]+(\+[A-Za-z_]+)*$"


def parse_languages(spec: str) -> list[str]:
    """'eng+spa' -> ['eng', 'spa'], verified against the installed Tesseract data."""
    wanted = [p for p in spec.split("+") if p]
    try:
        installed = set(pytesseract.get_languages(config=""))
    except pytesseract.TesseractError:
        raise ToolError("Tesseract is not working in this environment.") from None
    missing = [w for w in wanted if w not in installed]
    if missing:
        have = ", ".join(sorted(installed - {"osd"}))
        raise ToolError(f"OCR language(s) not installed: {', '.join(missing)}. Installed: {have}.")
    return wanted
