from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.core.errors import ApiError, Cancelled, ToolError
from app.core.tool import ProgressFn, Tool, ToolContext

log = logging.getLogger("toolbox.jobs")

JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
FINAL_STATES = ("done", "failed", "cancelled")


@dataclass
class ExecResult:
    outputs: list[Path] = field(default_factory=list)
    text: str | None = None


def validate_params(tool: Tool, raw: dict) -> BaseModel:
    try:
        return tool.Params.model_validate(raw)
    except ValidationError as e:
        raise ApiError(
            422,
            "validation_error",
            "Invalid parameters.",
            detail=json.loads(e.json(include_url=False, include_context=False)),
        ) from None


def _collect(
    tool: Tool, result: list[Path] | str, ctx: ToolContext, texts: list[str]
) -> list[Path]:
    if isinstance(result, str):
        texts.append(result)
        return []
    out_root = ctx.out_dir.resolve()
    outputs: list[Path] = []
    for p in result:
        p = Path(p)
        if out_root not in p.resolve().parents:
            raise RuntimeError(f"{tool.id} returned a file outside its output folder: {p}")
        outputs.append(p)
    return outputs


def execute(
    tool: Tool,
    files: list[Path],
    params: BaseModel,
    workdir: Path,
    progress: ProgressFn | None = None,
    ctx: ToolContext | None = None,
) -> ExecResult:
    """Run a tool synchronously. Shared by the job runner, pipelines and the CLI.

    Batch tools (written for one file) are called once per file when several are given.
    """
    if ctx is None:
        ctx = ToolContext(workdir=workdir)
    if progress is not None:
        ctx.progress = progress
    ctx.out_dir.mkdir(parents=True, exist_ok=True)

    texts: list[str] = []
    outputs: list[Path] = []

    if tool.batch and tool.max_files == 1 and len(files) > 1:
        base, n = ctx.progress, len(files)
        try:
            for i, f in enumerate(files):
                ctx.check_cancelled()

                def sub(frac: float, msg: str, i: int = i, f: Path = f) -> None:
                    base((i + frac) / n, f"{f.name}: {msg}" if msg else f.name)

                ctx.progress = sub
                result = tool.run([f], params, ctx)
                if isinstance(result, str):
                    texts.append(f"=== {f.name} ===\n{result}")
                else:
                    outputs.extend(_collect(tool, result, ctx, texts))
        finally:
            ctx.progress = base
    else:
        outputs = _collect(tool, tool.run(files, params, ctx), ctx, texts)

    if texts:
        text = "\n\n".join(texts)
        (ctx.out_dir / "result.txt").write_text(text, encoding="utf-8")
        return ExecResult(outputs=[ctx.out_dir / "result.txt", *outputs], text=text)
    return ExecResult(outputs=outputs)


@dataclass
class Job:
    id: str
    tool_id: str
    status: str = "queued"  # queued | running | done | failed | cancelled
    progress: float = 0.0
    message: str = ""
    outputs: list[dict] = field(default_factory=list)
    text: str | None = None
    error: dict | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tool_id": self.tool_id,
            "status": self.status,
            "progress": round(self.progress, 3),
            "message": self.message,
            "outputs": self.outputs,
            "text": self.text,
            "error": self.error,
            "created_at": self.created_at,
        }


Runner = Callable[[ToolContext], ExecResult]


class JobManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, settings.workers), thread_name_prefix="job"
        )
        self._jobs: dict[str, Job] = {}
        self._ctxs: dict[str, ToolContext] = {}
        self._lock = threading.Lock()
        self._load_existing()

    # -- paths -----------------------------------------------------------
    def job_dir(self, job_id: str) -> Path:
        if not JOB_ID_RE.match(job_id):
            raise ApiError(404, "not_found", "Job not found.")
        return self.settings.jobs_dir / job_id

    # -- persistence -----------------------------------------------------
    def _persist(self, job: Job) -> None:
        d = self.settings.jobs_dir / job.id
        if not d.exists():
            return
        tmp = d / "job.json.tmp"
        tmp.write_text(json.dumps(job.to_dict()), encoding="utf-8")
        tmp.replace(d / "job.json")

    def _load_existing(self) -> None:
        for d in self.settings.jobs_dir.iterdir():
            f = d / "job.json"
            if not (d.is_dir() and f.exists() and JOB_ID_RE.match(d.name)):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                job = Job(**data)
            except Exception:  # corrupt state: let the sweeper remove it
                continue
            if job.status in ("queued", "running"):
                job.status = "failed"
                job.error = {"code": "interrupted", "message": "Server restarted during the job."}
            self._jobs[job.id] = job

    # -- lifecycle -------------------------------------------------------
    def allocate(self) -> tuple[str, Path]:
        job_id = uuid.uuid4().hex
        d = self.settings.jobs_dir / job_id
        (d / "in").mkdir(parents=True)
        return job_id, d

    def discard(self, job_id: str) -> None:
        with self._lock:
            ctx = self._ctxs.pop(job_id, None)
        if ctx is not None:
            ctx.cancel()  # kill anything still running before deleting its folder
        shutil.rmtree(self.settings.jobs_dir / job_id, ignore_errors=True)
        with self._lock:
            self._jobs.pop(job_id, None)

    def submit(self, job_id: str, label: str, runner: Runner) -> Job:
        """Queue any callable that takes a ToolContext and returns an ExecResult."""
        job = Job(id=job_id, tool_id=label)
        ctx = ToolContext(workdir=self.settings.jobs_dir / job_id)
        with self._lock:
            self._jobs[job_id] = job
            self._ctxs[job_id] = ctx
        self._persist(job)
        self._pool.submit(self._run, job, ctx, runner)
        return job

    def submit_tool(self, job_id: str, tool: Tool, files: list[Path], params: BaseModel) -> Job:
        workdir = self.settings.jobs_dir / job_id
        return self.submit(
            job_id, tool.id, lambda ctx: execute(tool, files, params, workdir, ctx=ctx)
        )

    def get(self, job_id: str) -> Job:
        self.job_dir(job_id)  # validates the id format
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ApiError(404, "not_found", "Job not found (it may have expired).")
        return job

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status in FINAL_STATES:
            return job
        with self._lock:
            ctx = self._ctxs.get(job_id)
        if ctx is not None:
            ctx.cancel()
        if job.status == "queued":  # never started: finish it right here
            job.status = "cancelled"
            job.message = "Cancelled"
            self._persist(job)
        return job

    def _run(self, job: Job, ctx: ToolContext, runner: Runner) -> None:
        if job.status == "cancelled":
            return
        job.status = "running"
        self._persist(job)

        def progress(fraction: float, message: str) -> None:
            job.progress = max(0.0, min(1.0, fraction))
            job.message = message

        ctx.progress = progress
        try:
            result = runner(ctx)
            job.outputs = [
                {
                    "name": p.name,
                    "size": p.stat().st_size,
                    "url": f"/api/jobs/{job.id}/files/{quote(p.name)}",
                }
                for p in result.outputs
            ]
            job.text = result.text
            job.progress = 1.0
            job.message = "Done"
            job.status = "done"
        except Cancelled:
            job.status = "cancelled"
            job.message = "Cancelled"
        except ToolError as e:
            job.status = "failed"
            job.error = {"code": "tool_error", "message": str(e)}
        except Exception:
            log.exception("Job %s (%s) crashed", job.id, job.tool_id)
            job.status = "failed"
            job.error = {"code": "internal", "message": "The tool crashed. Check the server log."}
        finally:
            with self._lock:
                self._ctxs.pop(job.id, None)
            self._persist(job)

    # -- cleanup ---------------------------------------------------------
    def sweep(self) -> int:
        """Delete job folders older than the TTL. Returns how many were removed."""
        cutoff = time.time() - self.settings.job_ttl_min * 60
        removed = 0
        for d in self.settings.jobs_dir.iterdir():
            if not d.is_dir():
                continue
            job = self._jobs.get(d.name)
            if job is not None and job.status in ("queued", "running"):
                continue
            try:
                mtime = d.stat().st_mtime
            except OSError:
                continue
            created = job.created_at if job else mtime
            if min(created, mtime) < cutoff:
                self.discard(d.name)
                removed += 1
        return removed

    def shutdown(self) -> None:
        with self._lock:
            ctxs = list(self._ctxs.values())
        for c in ctxs:
            c.cancel()
        self._pool.shutdown(wait=False, cancel_futures=True)
