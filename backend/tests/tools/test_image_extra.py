import pytest
from PIL import Image
from pypdf import PdfReader

from app.core.errors import ToolError
from app.tools.image.compress import CompressImage
from app.tools.image.crop_rotate import CropRotateImage
from app.tools.image.favicon import Favicon
from app.tools.image.resize import ResizeImage
from app.tools.image.strip_exif import StripExif
from app.tools.image.to_pdf import ImagesToPdf


def size_of(path):
    with Image.open(path) as im:
        return im.size


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"mode": "width", "width": 200}, (200, 150)),
        ({"mode": "height", "height": 100}, (133, 100)),
        ({"mode": "percent", "percent": 50}, (200, 150)),
        ({"mode": "fit_box", "width": 100, "height": 100}, (100, 75)),
        ({"mode": "exact", "width": 50, "height": 60}, (50, 60)),
    ],
)
def test_resize_modes(make_image, run_tool, params, expected):
    (out,) = run_tool(ResizeImage, [make_image("p.png", (400, 300))], **params)
    assert size_of(out) == expected


def test_resize_without_upscale(make_image, run_tool):
    (out,) = run_tool(
        ResizeImage, [make_image("p.png", (400, 300))], mode="width", width=800, allow_upscale=False
    )
    assert size_of(out) == (400, 300)


def test_resize_keeps_format(make_image, run_tool):
    (out,) = run_tool(ResizeImage, [make_image("p.jpg")], mode="percent", percent=25)
    assert out.suffix == ".jpg"


def test_compress_jpeg_gets_smaller(make_image, run_tool):
    src = make_image("noise.jpg", (600, 600), noisy=True)
    (out,) = run_tool(CompressImage, [src], quality=30)
    assert out.stat().st_size < src.stat().st_size


def test_compress_png_quantizes(make_image, run_tool):
    src = make_image("noise.png", (300, 300), noisy=True)
    (out,) = run_tool(CompressImage, [src], png_colors=32)
    assert out.stat().st_size < src.stat().st_size


def test_compress_keeps_original_when_no_gain(tmp_path, run_tool):
    src = tmp_path / "dot.png"
    Image.new("RGB", (1, 1), "white").save(src)
    (out,) = run_tool(CompressImage, [src])
    assert out.read_bytes() == src.read_bytes()  # and the file really exists (regression)


def test_compress_max_side(make_image, run_tool):
    (out,) = run_tool(CompressImage, [make_image("big.jpg", (1600, 800))], max_side=400, quality=80)
    assert size_of(out) == (400, 200)


def test_crop_rotate_flip(make_image, run_tool):
    src = make_image("c.png", (400, 300))
    (cropped,) = run_tool(
        CropRotateImage, [src], crop_left=100, crop_top=50, crop_right=100, crop_bottom=50
    )
    assert size_of(cropped) == (200, 200)

    (rotated,) = run_tool(CropRotateImage, [src], rotate=90)
    assert size_of(rotated) == (300, 400)

    (flipped,) = run_tool(CropRotateImage, [src], flip="horizontal")
    with Image.open(flipped) as im:  # red square was top-left, now top-right
        assert im.getpixel((395, 5))[0] > 200 and im.getpixel((5, 5))[0] < 100


def test_crop_everything_is_an_error(make_image, run_tool):
    with pytest.raises(ToolError, match="whole"):
        run_tool(CropRotateImage, [make_image("c.png", (100, 100))], crop_left=60, crop_right=60)


def test_strip_exif_removes_metadata_and_keeps_upright(make_image, run_tool):
    src = make_image("photo.jpg", (400, 300), exif=True)
    with Image.open(src) as im:
        assert im.getexif().get(0x010F) == "TestCam"
    (out,) = run_tool(StripExif, [src])
    with Image.open(out) as im:
        assert 0x010F not in im.getexif() and 0x0112 not in im.getexif()
        assert im.size == (300, 400)  # orientation 6 was applied to the pixels first


def test_images_to_pdf_fit_and_a4(make_image, run_tool):
    imgs = [
        make_image("a.png", (200, 100)),
        make_image("b.jpg", (100, 200)),
        make_image("c.png", (50, 50)),
    ]
    (out,) = run_tool(ImagesToPdf, imgs, output_name="album")
    assert out.name == "album.pdf" and len(PdfReader(out).pages) == 3

    (a4,) = run_tool(ImagesToPdf, imgs[:2], page_size="a4")
    pages = PdfReader(a4).pages
    portrait, landscape = pages[1], pages[0]
    assert float(landscape.mediabox.width) > float(landscape.mediabox.height)  # wide picture
    assert float(portrait.mediabox.height) > float(portrait.mediabox.width)


def test_favicon_set(make_image, run_tool):
    outs = run_tool(Favicon, [make_image("logo.png", (300, 200))])
    names = {o.name for o in outs}
    assert {
        "favicon.ico",
        "icon-16.png",
        "icon-512.png",
        "apple-touch-icon.png",
        "head-snippet.html",
    } <= names
    by_name = {o.name: o for o in outs}
    assert size_of(by_name["icon-512.png"]) == (512, 512)
    assert size_of(by_name["apple-touch-icon.png"]) == (180, 180)
    with Image.open(by_name["favicon.ico"]) as ico:
        assert {16, 32, 48} <= {s[0] for s in ico.info["sizes"]}


def test_favicon_rejects_tiny_images(make_image, run_tool):
    with pytest.raises(ToolError, match="64"):
        run_tool(Favicon, [make_image("tiny.png", (32, 32))])
