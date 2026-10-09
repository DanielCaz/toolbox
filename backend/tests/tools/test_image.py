import pytest
from PIL import Image

from app.core.errors import ToolError
from app.tools.image.convert import ConvertImage


def _rgba_png(path, size=(64, 48)):
    Image.new("RGBA", size, (255, 0, 0, 0)).save(path)  # fully transparent red
    return path


def test_png_to_jpg_flattens_transparency_on_white(tmp_path, run_tool):
    src = _rgba_png(tmp_path / "logo.png")
    (out,) = run_tool(ConvertImage, [src], format="jpg", quality=80)
    assert out.name == "logo.jpg"
    with Image.open(out) as im:
        assert im.format == "JPEG" and im.mode == "RGB"
        r, g, b = im.getpixel((5, 5))
        assert min(r, g, b) > 240  # white, not black


@pytest.mark.parametrize(
    "fmt,pil_format",
    [
        ("png", "PNG"),
        ("webp", "WEBP"),
        ("gif", "GIF"),
        ("bmp", "BMP"),
        ("tiff", "TIFF"),
        ("ico", "ICO"),
    ],
)
def test_convert_formats(tmp_path, run_tool, fmt, pil_format):
    src = _rgba_png(tmp_path / "pic.png")
    (out,) = run_tool(ConvertImage, [src], format=fmt)
    with Image.open(out) as im:
        assert im.format == pil_format


def test_batch_conversion_and_name_collisions(tmp_path, run_tool):
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    a = _rgba_png(tmp_path / "x" / "same.png")
    b = _rgba_png(tmp_path / "y" / "same.png")
    outs = run_tool(ConvertImage, [a, b], format="webp")
    assert sorted(o.name for o in outs) == ["same-1.webp", "same.webp"]


def test_invalid_image_is_a_tool_error(tmp_path, run_tool):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image at all")
    with pytest.raises(ToolError):
        run_tool(ConvertImage, [bad], format="jpg")
