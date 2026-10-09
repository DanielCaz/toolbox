"""Optional heavy tools (Whisper, rembg) tested with stand-in modules - no model downloads."""

import subprocess
import sys
import types

import pytest
from PIL import Image

from app.core.errors import Cancelled, ToolError
from app.core.registry import Registry
from app.core.tool import ToolContext
from app.tools.image.remove_bg import RemoveBackground
from app.tools.media.transcribe import Transcribe, render, stamp


class FakeSeg:
    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


@pytest.fixture
def fake_whisper(monkeypatch, tmp_path):
    calls = {}
    mod = types.ModuleType("faster_whisper")

    class WhisperModel:
        def __init__(self, name, **kw):
            calls["model"], calls["kw"] = name, kw

        def transcribe(self, path, **kw):
            calls["path"], calls["tkw"] = path, kw
            segs = [
                FakeSeg(0.0, 1.2, " Hello there. "),
                FakeSeg(1.2, 2.0, ""),
                FakeSeg(2.0, 3.0, "Bye"),
            ]
            return iter(segs), None

    mod.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", mod)
    monkeypatch.setenv("TOOLBOX_MODEL_DIR", str(tmp_path / "models"))
    from app.config import get_settings

    get_settings.cache_clear()
    yield calls
    get_settings.cache_clear()


@pytest.fixture
def tone(tmp_path):
    path = tmp_path / "in" / "speech.wav"
    path.parent.mkdir()
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=3", str(path)],
        check=True,
    )
    return path


def test_timestamps_and_renderers():
    assert stamp(3723.456, comma=True) == "01:02:03,456"
    assert stamp(1.5, comma=False) == "00:00:01.500"
    segs = [(0.0, 1.0, "Hi"), (1.0, 2.5, "There")]
    assert render(segs, "txt") == "Hi\nThere\n"
    srt = render(segs, "srt")
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
    assert "2\n00:00:01,000 --> 00:00:02,500\nThere" in srt
    vtt = render(segs, "vtt")
    assert vtt.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi")


def test_transcribe_writes_text_and_subtitles(run_tool, fake_whisper, tone, tmp_path):
    [txt] = run_tool(Transcribe, [tone], format="txt", model="tiny", language="en")
    assert txt.read_text() == "Hello there.\nBye\n"  # blank segment dropped, text stripped
    assert fake_whisper["model"] == "tiny"
    assert fake_whisper["tkw"]["language"] == "en"
    assert fake_whisper["kw"]["download_root"] == str(tmp_path / "models")
    assert fake_whisper["path"].endswith("speech.wav")

    [srt] = run_tool(Transcribe, [tone], format="srt")
    assert "00:00:02,000 --> 00:00:03,000\nBye" in srt.read_text()


def test_transcribe_cancel_between_segments(tmp_path, fake_whisper, tone):
    ctx = ToolContext(workdir=tmp_path / "w")
    sys.modules["faster_whisper"].WhisperModel.transcribe = lambda self, p, **kw: (
        (ctx.cancel() or FakeSeg(0, 1, "x") for _ in range(3)),
        None,
    )
    tool = Transcribe()
    with pytest.raises(Cancelled):
        tool.run([tone], tool.Params(), ctx)


def test_transcribe_without_speech(run_tool, fake_whisper, tone):
    sys.modules["faster_whisper"].WhisperModel.transcribe = lambda self, p, **kw: (iter([]), None)
    with pytest.raises(ToolError, match="No speech"):
        run_tool(Transcribe, [tone])


def test_transcribe_model_load_failure_is_user_facing(run_tool, fake_whisper, tone, monkeypatch):
    def boom(self, name, **kw):
        raise OSError("offline")

    monkeypatch.setattr(sys.modules["faster_whisper"].WhisperModel, "__init__", boom)
    with pytest.raises(ToolError, match="Could not load the Whisper"):
        run_tool(Transcribe, [tone])


@pytest.fixture
def fake_rembg(monkeypatch, tmp_path):
    mod = types.ModuleType("rembg")
    seen = {}

    def new_session(name):
        seen["model"] = name
        return object()

    def remove(im, session=None):
        out = im.convert("RGBA")
        px = out.load()
        for x in range(out.width // 2):  # left half becomes transparent
            for y in range(out.height):
                px[x, y] = (0, 0, 0, 0)
        return out

    mod.new_session, mod.remove = new_session, remove
    monkeypatch.setitem(sys.modules, "rembg", mod)
    monkeypatch.setenv("TOOLBOX_MODEL_DIR", str(tmp_path / "models"))
    from app.config import get_settings

    get_settings.cache_clear()
    yield seen
    get_settings.cache_clear()


def test_remove_bg_transparent_and_white(run_tool, fake_rembg, make_image):
    src = make_image("p.png", size=(40, 20))
    [out] = run_tool(RemoveBackground, [src], model="u2net")
    assert fake_rembg["model"] == "u2net"
    im = Image.open(out)
    assert im.mode == "RGBA"
    assert im.getpixel((2, 5))[3] == 0 and im.getpixel((35, 15))[3] == 255

    [flat] = run_tool(RemoveBackground, [src], background="white")
    fim = Image.open(flat)
    assert fim.mode == "RGB" and fim.getpixel((2, 5)) == (255, 255, 255)


def test_optional_tools_hide_without_their_packages(monkeypatch):
    monkeypatch.setitem(sys.modules, "rembg", None)  # importing it now raises ImportError
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a, **k: None if name in ("rembg", "faster_whisper") else real(name, *a, **k),
    )
    reg = Registry()
    missing = {t.id: reg.missing(t) for t in reg.tools.values()}
    assert reg.describe(reg.get("image.remove_bg"))["available"] is False
    assert "python:rembg" in missing["image.remove_bg"]
    assert "python:faster_whisper" in missing["media.transcribe"]
