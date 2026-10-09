from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.media._common import MEDIA_TYPES, probe, run_ffmpeg


class TranscribeParams(BaseModel):
    model: Literal["tiny", "base", "small", "medium"] = Field(
        "base", description="Bigger = more accurate but slower. Downloaded on first use."
    )
    language: str = Field(
        "", max_length=8, description="Language code such as en or es. Blank = detect"
    )
    format: Literal["txt", "srt", "vtt"] = Field(
        "txt", description="txt = plain text · srt / vtt = subtitles with timestamps"
    )


def stamp(seconds: float, *, comma: bool) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{',' if comma else '.'}{ms:03d}"


def render(segments: list[tuple[float, float, str]], fmt: str) -> str:
    if fmt == "txt":
        return "\n".join(text for _, _, text in segments) + "\n"
    lines = ["WEBVTT", ""] if fmt == "vtt" else []
    for i, (start, end, text) in enumerate(segments, start=1):
        if fmt == "srt":
            lines.append(str(i))
        lines.append(f"{stamp(start, comma=fmt == 'srt')} --> {stamp(end, comma=fmt == 'srt')}")
        lines += [text, ""]
    return "\n".join(lines)


class Transcribe(Tool):
    id = "media.transcribe"
    name = "Transcribe speech to text"
    category = "media"
    description = "Turn speech in audio or video into text or subtitles, on this machine (Whisper)."
    accepts = MEDIA_TYPES
    batch = True
    slow = True
    requires = ["ffmpeg", "ffprobe"]
    requires_py = ["faster_whisper"]
    Params = TranscribeParams

    def run(self, files: list[Path], params: TranscribeParams, ctx: ToolContext):
        from faster_whisper import WhisperModel  # optional dependency

        src = files[0]
        info = probe(ctx, src)
        if not info["has_audio"]:
            raise ToolError(f"'{src.name}' has no audio track.")
        total = info["duration"]

        # 16 kHz mono WAV is what Whisper wants; doing it with ffmpeg keeps decoding cancellable
        wav = ctx.scratch("transcribe") / "speech.wav"
        run_ffmpeg(
            ctx, src, wav, ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"],
            duration=total, label="Preparing audio", timeout=1800,
        )  # fmt: skip
        ctx.progress(0.1, f"Loading the {params.model} model")
        models = get_settings().models_dir
        models.mkdir(parents=True, exist_ok=True)
        try:
            model = WhisperModel(
                params.model, device="cpu", compute_type="int8", download_root=str(models)
            )
        except Exception as exc:  # model download / load problems are user-facing
            raise ToolError(f"Could not load the Whisper '{params.model}' model: {exc}") from None

        seg_iter, _ = model.transcribe(str(wav), language=params.language or None, vad_filter=True)
        segments: list[tuple[float, float, str]] = []
        for seg in seg_iter:  # lazy: transcription happens while we iterate
            ctx.check_cancelled()
            text = seg.text.strip()
            if text:
                segments.append((seg.start, seg.end, text))
            if total:
                ctx.progress(0.1 + 0.88 * min(1.0, seg.end / total), "Transcribing")
        if not segments:
            raise ToolError(f"No speech was found in '{src.name}'.")

        out = ctx.out_unique(f"{src.stem}.{params.format}")
        out.write_text(render(segments, params.format), encoding="utf-8")
        return [out]
