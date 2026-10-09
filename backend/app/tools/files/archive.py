import tarfile
import zipfile
from pathlib import Path
from typing import Literal

import py7zr
from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.files import safe_name
from app.core.tool import Tool, ToolContext

MAX_MEMBERS = 5000
MAX_TOTAL_BYTES = 2 * 1024**3  # 2 GiB of extracted data per job (zip-bomb guard)
CHUNK = 1024 * 1024


class ArchiveParams(BaseModel):
    action: Literal["extract", "create"] = Field(
        "extract", description="extract: unpack an archive · create: pack the files you add"
    )
    format: Literal["zip", "tar.gz", "7z"] = Field("zip", description="Archive type (create only)")
    output_name: str = Field(
        "archive", max_length=100, description="Name without extension (create only)"
    )


def flat_name(member: str) -> str:
    """'docs/../x/readme.txt' → 'docs_x_readme.txt': no paths ever reach the disk."""
    parts = [p for p in member.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return safe_name("_".join(parts)) if parts else ""


class Budget:
    def __init__(self) -> None:
        self.members = 0
        self.bytes = 0

    def add_member(self) -> None:
        self.members += 1
        if self.members > MAX_MEMBERS:
            raise ToolError(
                f"The archive holds more than {MAX_MEMBERS} files; refusing to unpack it."
            )

    def add_bytes(self, n: int) -> None:
        self.bytes += n
        if self.bytes > MAX_TOTAL_BYTES:
            raise ToolError("The archive unpacks to more than 2 GB; refusing to unpack it.")


def _copy_limited(reader, dest: Path, budget: Budget) -> None:
    with dest.open("wb") as out:
        while chunk := reader.read(CHUNK):
            budget.add_bytes(len(chunk))
            out.write(chunk)


class Archive(Tool):
    id = "files.archive"
    name = "Zip, unzip and archives"
    category = "files"
    description = (
        "Create a zip, tar.gz or 7z from files, or unpack zip, tar, tar.gz/bz2/xz and 7z. "
        "Folders inside archives are flattened into file names."
    )
    accepts = ["*/*"]  # anything can be packed; the extract path checks the type itself
    max_files = None
    Params = ArchiveParams

    # -- create ----------------------------------------------------------
    def _create(self, files: list[Path], params: ArchiveParams, ctx: ToolContext) -> list[Path]:
        ext = {"zip": "zip", "tar.gz": "tar.gz", "7z": "7z"}[params.format]
        out = ctx.out_unique(f"{safe_name(params.output_name) or 'archive'}.{ext}")
        if params.format == "zip":
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, f in enumerate(files, start=1):
                    ctx.check_cancelled()
                    zf.write(f, arcname=f.name)
                    ctx.progress(i / len(files), f"Added {f.name}")
        elif params.format == "tar.gz":
            with tarfile.open(out, "w:gz") as tf:
                for i, f in enumerate(files, start=1):
                    ctx.check_cancelled()
                    tf.add(f, arcname=f.name)
                    ctx.progress(i / len(files), f"Added {f.name}")
        else:
            with py7zr.SevenZipFile(out, "w") as sz:
                for i, f in enumerate(files, start=1):
                    ctx.check_cancelled()
                    sz.write(f, arcname=f.name)
                    ctx.progress(i / len(files), f"Added {f.name}")
        return [out]

    # -- extract ---------------------------------------------------------
    def _extract(self, src: Path, ctx: ToolContext) -> list[Path]:
        budget = Budget()
        outputs: list[Path] = []

        def emit(member: str, reader) -> None:
            name = flat_name(member)
            if not name:
                return
            dest = ctx.out_unique(name)
            _copy_limited(reader, dest, budget)
            outputs.append(dest)
            ctx.progress(min(0.95, len(outputs) / 50), f"Unpacked {name}")

        try:
            if zipfile.is_zipfile(src):
                with zipfile.ZipFile(src) as zf:
                    for info in zf.infolist():
                        ctx.check_cancelled()
                        if info.is_dir():
                            continue
                        if info.flag_bits & 0x1:
                            raise ToolError(
                                "This zip is password protected, which is not supported."
                            )
                        budget.add_member()
                        with zf.open(info) as fh:
                            emit(info.filename, fh)
            elif tarfile.is_tarfile(src):
                with tarfile.open(src) as tf:
                    for m in tf:
                        ctx.check_cancelled()
                        if not m.isreg():  # skip dirs, symlinks, devices, hard links
                            continue
                        budget.add_member()
                        fh = tf.extractfile(m)
                        if fh is not None:
                            emit(m.name, fh)
            elif py7zr.is_7zfile(src):
                with py7zr.SevenZipFile(src) as sz:
                    if sz.needs_password():
                        raise ToolError("This 7z is password protected, which is not supported.")
                    entries = [e for e in sz.list() if not e.is_directory]
                    declared = Budget()  # sizes claimed by the header, checked before unpacking
                    for e in entries:
                        budget.add_member()
                        declared.add_bytes(e.uncompressed or 0)
                    stage = ctx.scratch("7z-stage")
                    for i, e in enumerate(entries):
                        ctx.check_cancelled()
                        # py7zr extracts one member at a time into a private staging folder
                        # (it rejects path traversal itself); we then flatten what it wrote.
                        sz.reset()
                        sz.extract(path=stage, targets=[e.filename])
                        staged = (stage / e.filename).resolve()
                        if (
                            not staged.is_relative_to(stage.resolve())
                            or (stage / e.filename).is_symlink()
                            or not staged.is_file()
                        ):
                            continue  # symlinks, devices and anything odd are skipped
                        with staged.open("rb") as fh:
                            emit(e.filename, fh)
                        staged.unlink()
                        ctx.progress(min(0.95, (i + 1) / len(entries)), f"Unpacked {e.filename}")
            else:
                raise ToolError(f"'{src.name}' is not a zip, tar or 7z archive.")
        except ToolError:
            raise
        except (zipfile.BadZipFile, tarfile.TarError, py7zr.Bad7zFile, EOFError, OSError):
            raise ToolError(f"'{src.name}' looks damaged and could not be unpacked.") from None

        if not outputs:
            raise ToolError("The archive is empty.")
        return outputs

    def run(self, files: list[Path], params: ArchiveParams, ctx: ToolContext):
        if params.action == "create":
            return self._create(files, params, ctx)
        if len(files) != 1:
            raise ToolError("Add exactly one archive to unpack.")
        return self._extract(files[0], ctx)
