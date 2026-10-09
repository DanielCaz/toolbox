from __future__ import annotations

import os
import signal
import subprocess
import threading
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel

from app.core.errors import Cancelled, ToolError

ProgressFn = Callable[[float, str], None]


class NoParams(BaseModel):
    """Params model for tools that take no options."""


def _no_progress(fraction: float, message: str) -> None:
    return None


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)  # the whole group: ffmpeg/soffice spawn children
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


@dataclass
class ToolContext:
    workdir: Path  # per-job temp dir, deleted after the TTL
    progress: ProgressFn = _no_progress  # progress(0.4, "page 4/10")
    cancel_event: threading.Event = field(default_factory=threading.Event)
    _procs: set = field(default_factory=set, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # -- output paths ----------------------------------------------------
    @property
    def out_dir(self) -> Path:
        d = self.workdir / "out"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def out(self, name: str) -> Path:
        """Path inside the job's output folder (created on demand)."""
        return self.out_dir / name

    def out_unique(self, name: str) -> Path:
        """Like out(), but never collides with an existing output (a.png, a-1.png...)."""
        path = self.out_dir / name
        stem, suffix, n = path.stem, path.suffix, 1
        while path.exists():
            path = self.out_dir / f"{stem}-{n}{suffix}"
            n += 1
        return path

    def scratch(self, name: str = "") -> Path:
        """A private temp folder inside the job dir (not part of the outputs)."""
        d = self.workdir / "scratch" / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def child(self, workdir: Path, progress: ProgressFn | None = None) -> ToolContext:
        """A context for a sub-step (pipelines). It shares this one's cancellation and process
        list, so cancelling the parent stops whatever the child is running."""
        return ToolContext(
            workdir=workdir,
            progress=progress or self.progress,
            cancel_event=self.cancel_event,
            _procs=self._procs,
            _lock=self._lock,
        )

    # -- cancellation ----------------------------------------------------
    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled

    def cancel(self) -> None:
        """Called from another thread: flag the job and kill any running subprocess."""
        self.cancel_event.set()
        with self._lock:
            procs = list(self._procs)
        for p in procs:
            _kill(p)

    # -- subprocesses ----------------------------------------------------
    def run_cmd(
        self,
        args: list,
        *,
        timeout: float = 900,
        cwd: Path | None = None,
        env: dict | None = None,
        on_line: Callable[[str], None] | None = None,
    ) -> str:
        """Run an external program (argument list, never a shell) with a timeout.

        stdout and stderr are merged and streamed line by line to ``on_line``.
        Cancelling the job kills the process group. Returns the last ~60 output lines.
        """
        self.check_cancelled()
        argv = [str(a) for a in args]
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                cwd=cwd,
                env=env,
                start_new_session=True,
            )
        except FileNotFoundError:
            raise ToolError(f"'{argv[0]}' is not installed on the server.") from None

        with self._lock:
            self._procs.add(proc)
        timed_out = threading.Event()

        def _on_timeout() -> None:
            timed_out.set()
            _kill(proc)

        timer = threading.Timer(timeout, _on_timeout)
        timer.start()
        tail: deque[str] = deque(maxlen=60)
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\n")
                tail.append(line)
                if on_line:
                    on_line(line)
            proc.wait()
        finally:
            timer.cancel()
            if proc.poll() is None:
                _kill(proc)
                proc.wait()
            with self._lock:
                self._procs.discard(proc)

        self.check_cancelled()
        if timed_out.is_set():
            raise ToolError(f"{Path(argv[0]).name} timed out after {int(timeout)} s.")
        if proc.returncode != 0:
            detail = "\n".join(list(tail)[-6:]).strip()
            raise ToolError(
                f"{Path(argv[0]).name} failed: {detail or f'exit code {proc.returncode}'}"
            )
        return "\n".join(tail)


class Tool(ABC):
    """Base class for every server-side tool.

    Subclass it anywhere under ``app/tools/`` and the registry discovers it.
    ``run`` takes files + validated params and returns output files or a string.
    """

    id: ClassVar[str]  # "pdf.merge"
    name: ClassVar[str]  # "Merge PDFs"
    category: ClassVar[str]  # "pdf"
    description: ClassVar[str] = ""
    accepts: ClassVar[list[str]] = []  # MIME patterns: ["application/pdf"], ["image/*"]
    min_files: ClassVar[int] = 1
    max_files: ClassVar[int | None] = 1  # None = unlimited
    # Batch mode: a tool written for exactly one file may be given many; the runner then
    # calls run() once per file and collects every output.
    batch: ClassVar[bool] = False
    output: ClassVar[str] = "files"  # "files" | "text"
    slow: ClassVar[bool] = False  # hint for the UI; every run is a job anyway
    requires: ClassVar[list[str]] = []  # external binaries: ["tesseract", "gs"]
    requires_py: ClassVar[list[str]] = []  # optional Python modules: ["faster_whisper"]
    Params: ClassVar[type[BaseModel]] = NoParams

    def unmet(self) -> list[str]:
        """Extra availability requirements beyond binaries / modules (e.g. 'config:LLM').
        Return a list of human-readable names of what is missing; empty = ready."""
        return []

    @abstractmethod
    def run(self, files: list[Path], params: BaseModel, ctx: ToolContext) -> list[Path] | str: ...
