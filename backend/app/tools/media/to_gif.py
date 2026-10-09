from pathlib import Path

from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.media._common import VIDEO_ONLY, parse_time, probe, run_ffmpeg

MAX_SECONDS = 60


class ToGifParams(BaseModel):
    start: str = Field("", description="Start time: seconds or 0:05. Blank = beginning")
    duration: float = Field(5, gt=0, le=MAX_SECONDS, description="Length in seconds (max 60)")
    fps: int = Field(12, ge=1, le=30, description="Frames per second")
    width: int = Field(480, ge=64, le=1280, description="Width in pixels (height follows)")


class ToGif(Tool):
    id = "media.to_gif"
    name = "Video to GIF"
    category = "media"
    description = "Turn a clip of a video into an animated GIF."
    accepts = VIDEO_ONLY
    batch = True
    slow = True
    requires = ["ffmpeg", "ffprobe"]
    Params = ToGifParams

    def run(self, files: list[Path], params: ToGifParams, ctx: ToolContext):
        src = files[0]
        info = probe(ctx, src)
        if not info["has_video"]:
            raise ToolError(f"'{src.name}' has no video.")
        start = parse_time(params.start, field="start") or 0.0
        total = info["duration"]
        if total is not None and start >= total:
            raise ToolError(f"The start time is past the end of the video ({total:.1f} s).")
        length = params.duration if total is None else min(params.duration, total - start)
        # two-pass palette gives far better colours than ffmpeg's default GIF palette
        vf = (
            f"fps={params.fps},scale='min({params.width},iw)':-1:flags=lanczos,"
            "split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4"
        )
        pre: list = ["-ss", f"{start:.3f}"] if start else []
        args = ["-t", f"{length:.3f}", "-an", "-vf", vf, "-loop", "0"]
        out = ctx.out_unique(f"{src.stem}.gif")
        run_ffmpeg(ctx, src, out, args, duration=length, pre_input=pre, label="Making GIF")
        return [out]
