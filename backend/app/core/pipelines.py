"""Pipelines: chain tools so the outputs of one step feed the next.

A pipeline is plain data (name + ordered steps of {tool, params}); presets are saved as JSON
files under ``<data_dir>/pipelines``. Running one reuses ``execute`` for every step, so batch
mode, cancellation and progress behave exactly as for a single tool.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import unicodedata
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.core.errors import ApiError, ToolError
from app.core.files import check_inputs
from app.core.jobs import ExecResult, execute, validate_params
from app.core.registry import Registry
from app.core.tool import ToolContext

MAX_STEPS = 10
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")


class Step(BaseModel):
    tool: str = Field(min_length=1, max_length=80)
    params: dict = Field(default_factory=dict)


class PipelineDef(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field("", max_length=300)
    steps: list[Step] = Field(min_length=1, max_length=MAX_STEPS)


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:50].strip("-")
    return slug or "pipeline"


def validate_pipeline(registry: Registry, definition: PipelineDef, *, check_available=True) -> None:
    """Raise ApiError(422) naming the step that is wrong."""
    for i, step in enumerate(definition.steps, start=1):
        try:
            tool = registry.get(step.tool)
        except ApiError:
            raise ApiError(
                422, "validation_error", f"Step {i}: there is no tool '{step.tool}'."
            ) from None
        if check_available:
            missing = registry.missing(tool)
            if missing:
                raise ApiError(
                    422,
                    "validation_error",
                    f"Step {i} ({tool.name}) is unavailable: missing {', '.join(missing)}.",
                )
        try:
            validate_params(tool, step.params)
        except ApiError as e:
            raise ApiError(
                422, "validation_error", f"Step {i} ({tool.name}): invalid parameters.", e.detail
            ) from None
        if tool.output == "text" and i != len(definition.steps):
            raise ApiError(
                422,
                "validation_error",
                f"Step {i} ({tool.name}) produces text, so it must be the last step.",
            )


def run_pipeline(
    registry: Registry, definition: PipelineDef, files: list[Path], ctx: ToolContext
) -> ExecResult:
    """Run the steps in order and return the last step's outputs (copied into ``ctx.out_dir``)."""
    steps = definition.steps
    n = len(steps)
    current = list(files)
    final = ExecResult()

    for i, step in enumerate(steps):
        ctx.check_cancelled()
        tool = registry.get(step.tool)
        label = f"Step {i + 1}/{n} · {tool.name}"
        try:
            check_inputs(tool, current)
        except ApiError as e:
            raise ToolError(f"{label}: {e.message}") from None
        params = validate_params(tool, step.params)

        def progress(frac: float, msg: str, i: int = i, label: str = label) -> None:
            ctx.progress((i + frac) / n, f"{label} — {msg}" if msg else label)

        step_ctx = ctx.child(ctx.workdir / "steps" / str(i + 1), progress)
        ctx.progress(i / n, label)
        result = execute(tool, current, params, step_ctx.workdir, ctx=step_ctx)
        if not result.outputs:
            raise ToolError(f"{label} produced no files.")
        current = result.outputs
        final = result

    # Copy the final files into the job's own output folder (intermediates stay in steps/).
    delivered: list[Path] = []
    for p in final.outputs:
        dest = ctx.out_unique(p.name)
        shutil.copyfile(p, dest)
        delivered.append(dest)
    return ExecResult(outputs=delivered, text=final.text)


class PipelineStore:
    """Saved pipelines as one JSON file each; the file name (slug) is the pipeline id."""

    def __init__(self, directory: Path):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, pid: str) -> Path:
        if not SLUG_RE.match(pid):
            raise ApiError(404, "not_found", "Pipeline not found.")
        return self.dir / f"{pid}.json"

    def get(self, pid: str) -> PipelineDef:
        path = self._path(pid)
        try:
            return PipelineDef.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ApiError(404, "not_found", "Pipeline not found.") from None
        except (ValidationError, ValueError, OSError):
            raise ApiError(500, "corrupt_pipeline", f"Pipeline '{pid}' is damaged.") from None

    def list(self) -> list[dict]:
        out = []
        for f in sorted(self.dir.glob("*.json"), key=lambda f: f.stem):
            if not SLUG_RE.match(f.stem):
                continue
            try:
                d = self.get(f.stem)
            except ApiError:
                continue  # skip damaged files rather than break the list
            out.append({"id": f.stem, **d.model_dump()})
        return out

    def create(self, definition: PipelineDef) -> str:
        with self._lock:
            base, pid, n = slugify(definition.name), "", 1
            pid = base
            while (self.dir / f"{pid}.json").exists():
                n += 1
                pid = f"{base}-{n}"
            self._write(pid, definition)
        return pid

    def update(self, pid: str, definition: PipelineDef) -> None:
        with self._lock:
            if not self._path(pid).exists():
                raise ApiError(404, "not_found", "Pipeline not found.")
            self._write(pid, definition)

    def delete(self, pid: str) -> None:
        with self._lock:
            path = self._path(pid)
            if not path.exists():
                raise ApiError(404, "not_found", "Pipeline not found.")
            path.unlink()

    def _write(self, pid: str, definition: PipelineDef) -> None:
        path = self._path(pid)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(definition.model_dump(), indent=2), encoding="utf-8")
        tmp.replace(path)
