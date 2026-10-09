"""Watch-folder mode: drop a file into ``<root>/<pipeline-id>/`` and get the result in ``_out/``.

Layout, per pipeline folder::

    inbox/scan-to-pdf/          ← drop files here
    inbox/scan-to-pdf/_out/     ← results
    inbox/scan-to-pdf/_done/    ← originals that were processed
    inbox/scan-to-pdf/_failed/  ← originals that failed, each with <name>.error.txt

Polling (no OS-specific watcher) keeps this working on Docker volumes and network shares. A file
is only picked up once its size and modification time have stopped changing between two scans,
so half-copied files are left alone.
"""

from __future__ import annotations

import logging
import shutil
import threading
import uuid
from pathlib import Path

from app.core.errors import ApiError, Cancelled, ToolError
from app.core.files import dedupe_name
from app.core.pipelines import SLUG_RE, PipelineStore, run_pipeline
from app.core.registry import Registry
from app.core.tool import ToolContext

log = logging.getLogger("toolbox.watch")

TEMP_SUFFIXES = (".part", ".tmp", ".crdownload", ".download", ".partial", "~")


class Watcher:
    def __init__(
        self,
        registry: Registry,
        store: PipelineStore,
        root: Path,
        workdir: Path,
        interval: float = 2.0,
    ):
        self.registry, self.store = registry, store
        self.root, self.workdir, self.interval = root, workdir, interval
        self._seen: dict[Path, tuple[int, int]] = {}
        self._warned: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._current: ToolContext | None = None
        self.root.mkdir(parents=True, exist_ok=True)

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="watcher", daemon=True)
        self._thread.start()
        log.info("Watching %s every %.1f s", self.root, self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self._current is not None:
            self._current.cancel()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception:
                log.exception("Watch scan failed")
            self._stop.wait(self.interval)

    # -- scanning --------------------------------------------------------
    def folders(self) -> list[tuple[Path, str]]:
        found = []
        for d in sorted(self.root.iterdir()):
            if d.is_symlink() or not d.is_dir() or not SLUG_RE.match(d.name):
                continue
            try:
                self.store.get(d.name)
            except ApiError:
                if d.name not in self._warned:
                    self._warned.add(d.name)
                    log.warning("Folder %s has no pipeline with that id; ignoring it", d)
                continue
            found.append((d, d.name))
        return found

    @staticmethod
    def _candidate(p: Path) -> bool:
        return (
            p.is_file()
            and not p.is_symlink()
            and not p.name.startswith((".", "_"))
            and not p.name.endswith(TEMP_SUFFIXES)
        )

    def scan_once(self) -> list[Path]:
        """One pass over every pipeline folder. Returns the input files that were processed."""
        processed: list[Path] = []
        present: set[Path] = set()
        for folder, pid in self.folders():
            for f in sorted(folder.iterdir()):
                if self._stop.is_set():
                    return processed
                if not self._candidate(f):
                    continue
                present.add(f)
                st = f.stat()
                sig = (st.st_size, int(st.st_mtime_ns))
                if self._seen.get(f) != sig:
                    self._seen[f] = sig  # changed (or new): wait for the next scan
                    continue
                self._process(folder, pid, f)
                self._seen.pop(f, None)
                processed.append(f)
        for gone in set(self._seen) - present:
            del self._seen[gone]
        return processed

    # -- processing ------------------------------------------------------
    def _process(self, folder: Path, pid: str, src: Path) -> None:
        definition = self.store.get(pid)
        job_dir = self.workdir / uuid.uuid4().hex
        ctx = ToolContext(workdir=job_dir)
        self._current = ctx
        try:
            result = run_pipeline(self.registry, definition, [src], ctx)
            out_dir = folder / "_out"
            out_dir.mkdir(exist_ok=True)
            for p in result.outputs:
                name = f"{src.stem}.txt" if p.name == "result.txt" else p.name
                shutil.copyfile(p, out_dir / dedupe_name(out_dir, name))
            self._file_away(folder, "_done", src)
            log.info("%s: processed %s", pid, src.name)
        except Cancelled:
            log.info("%s: stopped while processing %s", pid, src.name)
        except ToolError as e:
            self._fail(folder, src, str(e))
        except Exception:
            log.exception("%s: crashed on %s", pid, src.name)
            self._fail(folder, src, "The pipeline crashed. Check the server log.")
        finally:
            self._current = None
            shutil.rmtree(job_dir, ignore_errors=True)

    def _file_away(self, folder: Path, sub: str, src: Path) -> Path:
        dest_dir = folder / sub
        dest_dir.mkdir(exist_ok=True)
        dest = dest_dir / dedupe_name(dest_dir, src.name)
        shutil.move(str(src), dest)
        return dest

    def _fail(self, folder: Path, src: Path, message: str) -> None:
        log.warning("%s: %s failed: %s", folder.name, src.name, message)
        dest = self._file_away(folder, "_failed", src)
        dest.with_name(dest.name + ".error.txt").write_text(message + "\n", encoding="utf-8")
