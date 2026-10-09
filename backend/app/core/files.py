from __future__ import annotations

import fnmatch
import re
import unicodedata
import zipfile
from pathlib import Path

import magic

from app.core.errors import ApiError
from app.core.tool import Tool

_SAFE = re.compile(r"[^A-Za-z0-9 ._()\-]")


def safe_name(name: str | None) -> str:
    """Sanitise a client-supplied file name so it is safe to use on disk."""
    base = (name or "").replace("\\", "/").split("/")[-1]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = _SAFE.sub("_", base).strip().lstrip(".")
    base = base[-120:]
    return base or "file"


def dedupe_name(directory: Path, name: str) -> str:
    candidate, n = name, 1
    stem, suffix = Path(name).stem, Path(name).suffix
    while (directory / candidate).exists():
        candidate = f"{stem}-{n}{suffix}"
        n += 1
    return candidate


def sniff_mime(path: Path) -> str:
    # from_file lets libmagic read as far as it needs (OOXML/ODF detection looks inside the zip)
    return magic.from_file(str(path), mime=True)


def mime_matches(mime: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    return any(fnmatch.fnmatch(mime, p) for p in patterns)


def check_inputs(tool: Tool, paths: list[Path]) -> None:
    """Validate file count and content type (by sniffing, never by extension)."""
    n = len(paths)
    if n < tool.min_files:
        raise ApiError(
            422,
            "validation_error",
            f"{tool.name} needs at least {tool.min_files} file(s); got {n}.",
        )
    if tool.max_files is not None and n > tool.max_files and not tool.batch:
        raise ApiError(
            422,
            "validation_error",
            f"{tool.name} accepts at most {tool.max_files} file(s); got {n}.",
        )
    for p in paths:
        mime = sniff_mime(p)
        if not mime_matches(mime, tool.accepts):
            raise ApiError(
                415,
                "unsupported_file",
                f"'{p.name}' looks like {mime}, which {tool.name} does not accept.",
                detail={"accepts": tool.accepts, "got": mime},
            )


def zip_outputs(out_dir: Path, zip_path: Path) -> Path:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.iterdir()):
            if f.is_file():
                zf.write(f, arcname=f.name)
    return zip_path
