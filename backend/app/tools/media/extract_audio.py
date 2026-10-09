from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.media._common import MEDIA_TYPES, probe, run_ffmpeg

SPEC = {
    "mp3": ["-c:a", "libmp3lame"],
    "m4a": ["-c:a", "aac"],
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
}


class ExtractAudioParams(BaseModel):
    to: Literal["mp3", "m4a", "wav", "flac"] = Field("mp3", description="Audio format")
    bitrate_k: int = Field(192, ge=64, le=320, description="Bitrate in kbit/s (mp3, m4a)")


class ExtractAudio(Tool):
    id = "media.extract_audio"
    name = "Extract audio from video"
    category = "media"
    description = "Pull the soundtrack out of a video as MP3, M4A, WAV or FLAC."
    accepts = MEDIA_TYPES
    batch = True
    slow = True
    requires = ["ffmpeg", "ffprobe"]
    Params = ExtractAudioParams

    def run(self, files: list[Path], params: ExtractAudioParams, ctx: ToolContext):
        src = files[0]
        info = probe(ctx, src)
        if not info["has_audio"]:
            raise ToolError(f"'{src.name}' has no audio track.")
        args = ["-vn", *SPEC[params.to]]
        if params.to in ("mp3", "m4a"):
            args += ["-b:a", f"{params.bitrate_k}k"]
        out = ctx.out_unique(f"{src.stem}.{params.to}")
        run_ffmpeg(ctx, src, out, args, duration=info["duration"], label="Extracting audio")
        return [out]
