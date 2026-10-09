from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.media._common import MEDIA_TYPES, probe, run_ffmpeg

AUDIO = {"mp3", "m4a", "ogg", "opus", "flac", "wav"}
VIDEO = {"mp4", "webm", "mkv"}

# target → ffmpeg codec arguments
CODECS: dict[str, list[str]] = {
    "mp3": ["-c:a", "libmp3lame"],
    "m4a": ["-c:a", "aac", "-movflags", "+faststart"],
    "ogg": ["-c:a", "libvorbis"],
    "opus": ["-c:a", "libopus"],
    "flac": ["-c:a", "flac"],
    "wav": ["-c:a", "pcm_s16le"],
    "mp4": [
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
    ],
    "webm": ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1", "-c:a", "libopus"],
    "mkv": [
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
    ],
}


class ConvertParams(BaseModel):
    to: Literal["mp3", "m4a", "ogg", "opus", "flac", "wav", "mp4", "webm", "mkv"] = Field(
        "mp4", description="Output format (audio formats drop the video)"
    )
    audio_bitrate_k: int = Field(
        160, ge=32, le=512, description="Audio bitrate in kbit/s (mp3, m4a, ogg, opus, video)"
    )


class MediaConvert(Tool):
    id = "media.convert"
    name = "Audio & video converter"
    category = "media"
    description = "Convert audio or video to MP3, M4A, OGG, Opus, FLAC, WAV, MP4, WebM or MKV."
    accepts = MEDIA_TYPES
    batch = True
    slow = True
    requires = ["ffmpeg", "ffprobe"]
    Params = ConvertParams

    def run(self, files: list[Path], params: ConvertParams, ctx: ToolContext):
        src = files[0]
        info = probe(ctx, src)
        if params.to in VIDEO and not info["has_video"]:
            raise ToolError(f"'{src.name}' has no video; pick an audio format.")
        args: list = []
        if params.to in AUDIO:
            args += ["-vn"]
        args += list(CODECS[params.to])
        if params.to not in ("flac", "wav"):
            args += ["-b:a", f"{params.audio_bitrate_k}k"]
        args += ["-map_metadata", "0"]
        out = ctx.out_unique(f"{src.stem}.{params.to}")
        run_ffmpeg(ctx, src, out, args, duration=info["duration"], label=f"Converting {src.name}")
        return [out]
