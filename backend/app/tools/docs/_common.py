"""LibreOffice helper shared by the document tools (underscore prefix = not a tool)."""

from __future__ import annotations

import os
from pathlib import Path

from app.core.errors import ToolError
from app.core.tool import ToolContext


def soffice_convert(
    ctx: ToolContext, src: Path, target: str, outdir: Path, *, timeout: float = 240
) -> Path:
    """Convert ``src`` with headless LibreOffice. ``target`` is e.g. 'pdf' or
    'pdf:writer_web_pdf_Export'. Returns the produced file.

    Each job gets its own LibreOffice profile so parallel jobs never fight over a lock.
    """
    profile = ctx.scratch("lo-profile")
    env = {**os.environ, "HOME": str(profile)}
    outdir.mkdir(parents=True, exist_ok=True)
    ext = target.split(":")[0]
    expected = outdir / f"{src.stem}.{ext}"
    expected.unlink(missing_ok=True)

    output = ctx.run_cmd(
        [
            "soffice",
            f"-env:UserInstallation=file://{profile}",
            "--headless",
            "--norestore",
            "--nolockcheck",
            "--nodefault",
            "--nofirststartwizard",
            "--convert-to",
            target,
            "--outdir",
            outdir,
            src,
        ],
        timeout=timeout,
        env=env,
    )
    # soffice exits 0 even when it could not load the file, so check for the output itself
    if not expected.exists() or expected.stat().st_size == 0:
        hint = output.strip().splitlines()[-1] if output.strip() else "no output"
        raise ToolError(f"LibreOffice could not convert '{src.name}' ({hint}).")
    return expected
