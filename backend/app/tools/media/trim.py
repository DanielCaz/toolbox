from pathlib import Path

from pydantic import BaseModel, Field

from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.media._common import MEDIA_TYPES, parse_time, probe, run_ffmpeg


class TrimParams(BaseModel):
    start: str = Field("", description="Start time: seconds (90) or 1:30. Blank = beginning")
    end: str = Field("", description="End time: seconds or 1:30. Blank = end of file")
    precise: bool = Field(
        False,
        description="Re-encode for frame-accurate cuts (slower). Off = instant copy that "
        "snaps to the nearest keyframe",
    )


class MediaTrim(Tool):
    id = "media.trim"
    name = "Trim audio or video"
    category = "media"
    description = "Cut a section out of an audio or video file."
    accepts = MEDIA_TYPES
    batch = True
    slow = True
    requires = ["ffmpeg", "ffprobe"]
    Params = TrimParams

    def run(self, files: list[Path], params: TrimParams, ctx: ToolContext):
        src = files[0]
        info = probe(ctx, src)
        start = parse_time(params.start, field="start") or 0.0
        end = parse_time(params.end, field="end")
        total = info["duration"]
        if end is None:
            end = total
        if total is not None and start >= total:
            raise ToolError(f"The start time is past the end of the file ({total:.1f} s).")
        if end is not None and end <= start:
            raise ToolError("The end time must be after the start time.")
        length = (end - start) if end is not None else None

        # -ss before -i seeks fast; with re-encoding it is still frame accurate in modern ffmpeg
        pre: list = ["-ss", f"{start:.3f}"] if start else []
        args: list = []
        if length is not None:
            args += ["-t", f"{length:.3f}"]
        if not params.precise:
            args += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        out = ctx.out_unique(f"{src.stem}-trim{src.suffix.lower() or '.mp4'}")
        run_ffmpeg(ctx, src, out, args, duration=length, pre_input=pre, label="Trimming")
        return [out]
