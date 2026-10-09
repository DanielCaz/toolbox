"""ffmpeg helpers shared by the media tools (underscore prefix = not a tool)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.core.errors import ToolError
from app.core.tool import ToolContext

MEDIA_TYPES = ["video/*", "audio/*", "application/ogg", "application/mp4", "application/x-matroska"]
VIDEO_ONLY = ["video/*", "application/mp4", "application/x-matroska", "application/ogg"]

_TIME = re.compile(r"^(?:(?:(\d+):)?(\d{1,2}):)?(\d+(?:\.\d+)?)$")


def parse_time(text: str, *, field: str = "time") -> float | None:
    """'90', '1:30', '01:02:03.5' → seconds. Blank → None."""
    text = (text or "").strip()
    if not text:
        return None
    m = _TIME.match(text)
    if not m:
        raise ToolError(f"Could not read {field} '{text}'. Use seconds (90) or 1:30 / 0:01:30.5.")
    h, mnt, sec = m.groups()
    return int(h or 0) * 3600 + int(mnt or 0) * 60 + float(sec)


def probe(ctx: ToolContext, src: Path) -> dict:
    """Return ffprobe's view of the file: {'duration': s|None, 'has_video': bool, 'has_audio': bool,
    'height': int|None}. Raises ToolError for files ffmpeg cannot read."""
    lines: list[str] = []  # run_cmd only keeps a short tail, so collect the JSON ourselves
    ctx.run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            src,
        ],
        timeout=60,
        on_line=lines.append,
    )
    text = "\n".join(lines)
    try:
        info = json.loads(text[text.index("{") :])
    except ValueError:
        raise ToolError(f"'{src.name}' is not a media file ffmpeg can read.") from None
    streams = info.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video" and not _is_cover(s)]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if not video and not audio:
        raise ToolError(f"'{src.name}' has no audio or video streams.")
    try:
        duration = float(info.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    height = video[0].get("height") if video else None
    return {
        "duration": duration,
        "has_video": bool(video),
        "has_audio": bool(audio),
        "height": height,
    }


def _is_cover(stream: dict) -> bool:
    return bool(stream.get("disposition", {}).get("attached_pic"))


def run_ffmpeg(
    ctx: ToolContext,
    src: Path,
    out: Path,
    args: list,
    *,
    duration: float | None,
    pre_input: list | None = None,
    label: str = "Encoding",
    timeout: float = 3600,
) -> Path:
    """Run ffmpeg ``[pre_input] -i src [args] out`` and report real progress.

    ``duration`` is the length of the *output* in seconds (None = unknown → no percentage).
    """
    cmd: list = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        "-nostats",
        "-protocol_whitelist",
        "file",
        *(pre_input or []),
        "-i",
        src,
        *args,
        out,
    ]

    def on_line(line: str) -> None:
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            # both keys are in microseconds (ffmpeg's 'out_time_ms' is a long-standing misnomer)
            try:
                done = int(line.split("=", 1)[1]) / 1_000_000
            except ValueError:
                return
            if duration and duration > 0 and done >= 0:
                ctx.progress(min(0.99, done / duration), label)

    ctx.run_cmd(cmd, timeout=timeout, on_line=on_line)
    if not out.exists() or out.stat().st_size == 0:
        raise ToolError(f"ffmpeg produced no output for '{src.name}'.")
    return out
