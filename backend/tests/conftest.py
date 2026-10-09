from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas

from app.config import Settings
from app.core.tool import ToolContext
from app.main import create_app

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract missing")
needs_ocr_pdf = pytest.mark.skipif(
    shutil.which("tesseract") is None or shutil.which("gs") is None,
    reason="tesseract/ghostscript missing",
)


# --- fixture factories ---------------------------------------------------
@pytest.fixture
def make_pdf(tmp_path):
    """make_pdf(name, pages=3) -> a text PDF whose page N says 'Page N of <name>'."""

    def _make(name: str = "doc.pdf", pages: int = 3) -> Path:
        path = tmp_path / "inputs" / name
        path.parent.mkdir(exist_ok=True)
        c = canvas.Canvas(str(path))
        for n in range(1, pages + 1):
            c.setFont("Helvetica", 24)
            c.drawString(72, 700, f"Page {n} of {Path(name).stem}")
            c.showPage()
        c.save()
        return path

    return _make


@pytest.fixture
def make_text_image(tmp_path):
    """make_text_image(name, text) -> a PNG with large black text on white."""

    def _make(name: str = "text.png", text: str = "HELLO TOOLBOX 123") -> Path:
        path = tmp_path / "inputs" / name
        path.parent.mkdir(exist_ok=True)
        img = Image.new("RGB", (1000, 220), "white")
        ImageDraw.Draw(img).text((40, 60), text, fill="black", font=ImageFont.load_default(size=80))
        img.save(path)
        return path

    return _make


@pytest.fixture
def make_scanned_pdf(make_text_image, tmp_path):
    """An image-only PDF (no text layer), like a scan."""

    def _make(name: str = "scan.pdf", text: str = "HELLO TOOLBOX 123") -> Path:
        img_path = make_text_image(f"{Path(name).stem}-src.png", text)
        out = tmp_path / "inputs" / name
        Image.open(img_path).convert("RGB").save(out, "PDF", resolution=150)
        return out

    return _make


@pytest.fixture
def run_tool(tmp_path):
    """run_tool(ToolClass, files, **params) -> the tool's result, run in a temp workdir."""

    def _run(tool_cls, files, **params):
        tool = tool_cls()
        ctx = ToolContext(workdir=tmp_path / "work")
        return tool.run([Path(f) for f in files], tool.Params(**params), ctx)

    return _run


# --- API client ----------------------------------------------------------
@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        static_dir=tmp_path / "no-static",
        workers=2,
        job_ttl_min=60,
        max_upload_mb=5,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def make_image(tmp_path):
    """make_image(name, size, exif=False, noisy=False) -> an image file in the format of `name`."""
    import os

    def _make(name="photo.jpg", size=(400, 300), exif=False, noisy=False, mode="RGB"):
        path = tmp_path / "inputs" / name
        path.parent.mkdir(exist_ok=True)
        if noisy:
            img = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
        else:
            img = Image.new("RGB", size, (30, 120, 200))
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, size[0] // 2, size[1] // 2), fill=(220, 40, 40))  # red top-left
            draw.rectangle((size[0] // 2, size[1] // 2, size[0], size[1]), fill=(40, 200, 60))
        if mode != "RGB":
            img = img.convert(mode)
        kwargs = {}
        if exif:
            data = Image.Exif()
            data[0x010F] = "TestCam"  # Make
            data[0x0112] = 6  # Orientation: rotate 90° CW to display
            kwargs["exif"] = data
        img.save(path, **kwargs)
        return path

    return _make


@pytest.fixture
def run_execute(tmp_path):
    """run_execute(ToolClass, files, **params) -> ExecResult via the real runner (batch aware)."""
    from app.core.jobs import execute

    def _run(tool_cls, files, **params):
        tool = tool_cls()
        return execute(tool, [Path(f) for f in files], tool.Params(**params), tmp_path / "job")

    return _run
