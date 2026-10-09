"""ffmpeg-backed media tools, tested against tiny clips synthesised with ffmpeg itself."""

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from app.core.errors import Cancelled, ToolError
from app.core.tool import ToolContext
from app.tools.media._common import parse_time, probe
from app.tools.media.compress_video import CompressVideo
from app.tools.media.convert import MediaConvert
from app.tools.media.extract_audio import ExtractAudio
from app.tools.media.to_gif import ToGif
from app.tools.media.trim import MediaTrim

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")


def ffprobe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
         str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return json.loads(out)


def duration(path: Path) -> float:
    return float(ffprobe(path)["format"]["duration"])


@pytest.fixture
def make_video(tmp_path):
    """make_video(name, seconds, size, audio) -> a small test clip (testsrc + sine)."""

    def _make(name="clip.mp4", seconds=4, size="320x240", audio=True) -> Path:
        path = tmp_path / "inputs" / name
        path.parent.mkdir(exist_ok=True)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
               f"testsrc=duration={seconds}:size={size}:rate=15"]  # fmt: skip
        if audio:
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
        cmd += ["-g", "15", "-pix_fmt", "yuv420p", str(path)]  # frequent keyframes for copy-trim
        subprocess.run(cmd, check=True)
        return path

    return _make


@pytest.fixture
def make_audio(tmp_path):
    def _make(name="tone.wav", seconds=3) -> Path:
        path = tmp_path / "inputs" / name
        path.parent.mkdir(exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
             f"sine=frequency=440:duration={seconds}", str(path)],
            check=True,
        )  # fmt: skip
        return path

    return _make


def test_parse_time():
    assert parse_time("") is None
    assert parse_time("90") == 90
    assert parse_time("1:30") == 90
    assert parse_time("1:02:03.5") == 3723.5
    with pytest.raises(ToolError, match="Could not read"):
        parse_time("soon")
    with pytest.raises(ToolError):
        parse_time("-5")


def test_probe_reports_streams(tmp_path, make_video, make_audio):
    ctx = ToolContext(workdir=tmp_path / "w")
    v = probe(ctx, make_video())
    assert v["has_video"] and v["has_audio"] and v["height"] == 240
    assert v["duration"] == pytest.approx(4, abs=0.3)
    a = probe(ctx, make_audio())
    assert a["has_audio"] and not a["has_video"]


def test_convert_video_to_webm_and_mp4(run_tool, make_video):
    src = make_video("in.mp4", seconds=2)
    [out] = run_tool(MediaConvert, [src], to="webm")
    assert out.suffix == ".webm"
    codecs = {s["codec_name"] for s in ffprobe(out)["streams"]}
    assert {"vp9", "opus"} <= codecs

    mov = make_video("in2.mp4", seconds=2)
    [mkv] = run_tool(MediaConvert, [mov], to="mkv")
    assert duration(mkv) == pytest.approx(2, abs=0.3)


def test_convert_audio_formats(run_tool, make_audio):
    src = make_audio()
    for fmt, codec in [("mp3", "mp3"), ("m4a", "aac"), ("flac", "flac"), ("opus", "opus")]:
        [out] = run_tool(MediaConvert, [src], to=fmt)
        streams = ffprobe(out)["streams"]
        assert streams[0]["codec_name"] == codec, fmt
        assert duration(out) == pytest.approx(3, abs=0.4)


def test_convert_video_to_audio_drops_the_picture(run_tool, make_video):
    [out] = run_tool(MediaConvert, [make_video(seconds=2)], to="mp3")
    assert [s["codec_type"] for s in ffprobe(out)["streams"]] == ["audio"]


def test_convert_audio_to_video_format_is_refused(run_tool, make_audio):
    with pytest.raises(ToolError, match="no video"):
        run_tool(MediaConvert, [make_audio()], to="mp4")


def test_extract_audio(run_tool, make_video):
    [out] = run_tool(ExtractAudio, [make_video(seconds=3)], to="wav")
    info = ffprobe(out)
    assert [s["codec_type"] for s in info["streams"]] == ["audio"]
    assert duration(out) == pytest.approx(3, abs=0.3)


def test_extract_audio_without_track(run_tool, make_video):
    with pytest.raises(ToolError, match="no audio track"):
        run_tool(ExtractAudio, [make_video(audio=False)])


def test_trim_precise(run_tool, make_video):
    [out] = run_tool(MediaTrim, [make_video(seconds=6)], start="1", end="3.5", precise=True)
    assert duration(out) == pytest.approx(2.5, abs=0.2)


def test_trim_fast_copy_keeps_codecs(run_tool, make_video):
    [out] = run_tool(MediaTrim, [make_video(seconds=6)], start="0:02", end="0:04")
    assert duration(out) == pytest.approx(2, abs=1.0)  # copy snaps to keyframes
    assert ffprobe(out)["streams"][0]["codec_name"] == "h264"  # same as the source: not re-encoded


def test_trim_validation(run_tool, make_video):
    src = make_video(seconds=3)
    with pytest.raises(ToolError, match="after the start"):
        run_tool(MediaTrim, [src], start="2", end="1")
    with pytest.raises(ToolError, match="past the end"):
        run_tool(MediaTrim, [src], start="10")


def test_compress_video_scales_down(run_tool, make_video):
    src = make_video(seconds=2, size="640x480")
    [out] = run_tool(CompressVideo, [src], quality="small", max_height="360", speed="fast")
    video = next(s for s in ffprobe(out)["streams"] if s["codec_type"] == "video")
    assert video["codec_name"] == "h264"
    assert video["height"] == 360
    assert video["width"] == 480


def test_compress_never_enlarges(run_tool, make_video):
    [out] = run_tool(CompressVideo, [make_video(size="320x240", seconds=1)], max_height="720")
    video = next(s for s in ffprobe(out)["streams"] if s["codec_type"] == "video")
    assert video["height"] == 240


def test_to_gif(run_tool, make_video):
    [out] = run_tool(ToGif, [make_video(seconds=4)], start="1", duration=2, fps=10, width=160)
    info = ffprobe(out)
    assert info["streams"][0]["codec_name"] == "gif"
    assert info["streams"][0]["width"] == 160
    assert duration(out) == pytest.approx(2, abs=0.4)


def test_to_gif_rejects_audio_only_files_by_probe(run_tool, make_audio):
    with pytest.raises(ToolError, match="no video"):
        run_tool(ToGif, [make_audio()])


def test_unreadable_media_gives_a_clean_error(run_tool, tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"this is not a video" * 50)
    with pytest.raises(ToolError, match="failed"):
        run_tool(MediaConvert, [junk], to="mp3")


def test_progress_is_reported_in_between(tmp_path, make_video):
    seen: list[float] = []
    ctx = ToolContext(workdir=tmp_path / "w", progress=lambda f, m: seen.append(f))
    tool = MediaConvert()
    tool.run([make_video(seconds=6, size="640x480")], tool.Params(to="webm"), ctx)
    assert seen, "no progress reported"
    assert all(0 <= f <= 1 for f in seen)
    assert max(seen) > 0.3


def test_cancelling_stops_ffmpeg_quickly(tmp_path, make_video):
    # a long-ish VP9 encode so cancelling has something to interrupt
    src = make_video(seconds=60, size="1280x720")
    ctx = ToolContext(workdir=tmp_path / "w")
    tool = CompressVideo()
    result: dict = {}

    def target():
        try:
            tool.run([src], tool.Params(speed="slow", quality="high"), ctx)
            result["outcome"] = "finished"
        except Cancelled:
            result["outcome"] = "cancelled"

    t = threading.Thread(target=target)
    started = time.time()
    t.start()
    time.sleep(1.5)
    ctx.cancel()
    t.join(timeout=15)
    assert not t.is_alive(), "ffmpeg was not stopped"
    assert result["outcome"] == "cancelled"
    assert time.time() - started < 14
    leftover = subprocess.run(["pgrep", "-x", "ffmpeg"], capture_output=True)
    assert leftover.returncode != 0, "an ffmpeg process is still running"


def test_text_playlist_is_not_accepted_as_media(client):
    """An .m3u8 / concat list could make ffmpeg read other files; the MIME gate keeps it out."""
    playlist = b"#EXTM3U\n#EXTINF:1,\n/etc/passwd\n"
    r = client.post(
        "/api/tools/media.convert/run", files=[("files", ("x.mp4", playlist, "video/mp4"))]
    )
    assert r.status_code == 415
