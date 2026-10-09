from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.media._common import VIDEO_ONLY, probe, run_ffmpeg


class CompressVideoParams(BaseModel):
    quality: Literal["high", "balanced", "small"] = Field(
        "balanced", description="high = nearly lossless · balanced · small = smallest file"
    )
    max_height: Literal["original", "1080", "720", "480", "360"] = Field(
        "original", description="Shrink taller videos to this height (never enlarges)"
    )
    speed: Literal["fast", "medium", "slow"] = Field(
        "medium", description="Slower = smaller file at the same quality"
    )


CRF = {"high": 20, "balanced": 26, "small": 32}


class CompressVideo(Tool):
    id = "media.compress_video"
    name = "Compress video"
    category = "media"
    description = "Make a video smaller (H.264 MP4), optionally scaling it down."
    accepts = VIDEO_ONLY
    batch = True
    slow = True
    requires = ["ffmpeg", "ffprobe"]
    Params = CompressVideoParams

    def run(self, files: list[Path], params: CompressVideoParams, ctx: ToolContext):
        src = files[0]
        info = probe(ctx, src)
        if not info["has_video"]:
            raise ToolError(f"'{src.name}' has no video.")
        args: list = []
        if params.max_height != "original":
            # -2 keeps the width even; min() means small videos are never enlarged
            args += ["-vf", f"scale=-2:'min({int(params.max_height)},ih)'"]
        args += [
            "-c:v", "libx264", "-preset", params.speed, "-crf", str(CRF[params.quality]),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            "-map_metadata", "0",
        ]  # fmt: skip
        out = ctx.out_unique(f"{src.stem}-small.mp4")
        run_ffmpeg(ctx, src, out, args, duration=info["duration"], label="Compressing")
        if out.stat().st_size >= src.stat().st_size:
            ctx.progress(1.0, "Result is not smaller than the original")
        return [out]
