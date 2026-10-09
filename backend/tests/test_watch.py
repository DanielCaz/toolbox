"""Watch-folder mode, driven by calling scan_once() directly (no timing games)."""

import json
import os
import shutil
import subprocess
import sys
import time

import pytest

from app.core.pipelines import PipelineDef, PipelineStore
from app.core.registry import Registry
from app.core.watch import Watcher


@pytest.fixture
def setup(tmp_path):
    registry = Registry()
    store = PipelineStore(tmp_path / "pipelines")
    root = tmp_path / "inbox"
    watcher = Watcher(registry, store, root, tmp_path / "work", interval=0.05)
    return registry, store, root, watcher


def add(store, name, *steps):
    return store.create(PipelineDef(name=name, steps=[{"tool": t, "params": p} for t, p in steps]))


def settle(watcher):
    """A new file needs two scans: one to notice it, one to confirm it stopped changing."""
    first = watcher.scan_once()
    second = watcher.scan_once()
    return first + second


def test_file_is_processed_after_it_settles(setup, make_pdf):
    _, store, root, w = setup
    pid = add(store, "Numbered", ("pdf.page_numbers", {}))
    folder = root / pid
    folder.mkdir()
    src = folder / "doc.pdf"
    shutil.copy(make_pdf("doc.pdf", 2), src)

    assert w.scan_once() == []  # first sighting: not processed yet
    assert src.exists()
    assert w.scan_once() == [src]  # unchanged since last scan: processed
    assert not src.exists()
    assert (folder / "_done" / "doc.pdf").exists()
    [result] = list((folder / "_out").iterdir())
    assert result.suffix == ".pdf"


def test_growing_file_is_left_alone(setup):
    _, store, root, w = setup
    pid = add(store, "Numbered", ("pdf.page_numbers", {}))
    folder = root / pid
    folder.mkdir()
    f = folder / "big.pdf"
    f.write_bytes(b"%PDF-1.4 part one")
    w.scan_once()
    f.write_bytes(b"%PDF-1.4 part one and more bytes")  # still being written
    assert w.scan_once() == []
    assert f.exists()


def test_failures_go_to_failed_with_a_reason(setup):
    _, store, root, w = setup
    pid = add(store, "Numbered", ("pdf.page_numbers", {}))
    folder = root / pid
    folder.mkdir()
    (folder / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)  # not a PDF
    settle(w)
    assert (folder / "_failed" / "photo.png").exists()
    reason = (folder / "_failed" / "photo.png.error.txt").read_text()
    assert "Step 1/1" in reason
    assert not (folder / "_out").exists() or not list((folder / "_out").iterdir())


def test_text_results_are_named_after_the_input(setup, make_pdf):
    _, store, root, w = setup
    pid = add(store, "To text", ("pdf.extract_text", {}))
    folder = root / pid
    folder.mkdir()
    shutil.copy(make_pdf("report.pdf", 1), folder / "report.pdf")
    settle(w)
    assert (folder / "_out" / "report.txt").exists()


def test_ignores_temp_hidden_and_unknown_folders(setup, make_pdf):
    _, store, root, w = setup
    pid = add(store, "Numbered", ("pdf.page_numbers", {}))
    (root / pid).mkdir()
    (root / "no-such-pipeline").mkdir()
    (root / "Not A Slug!").mkdir()
    pdf = make_pdf("a.pdf", 1)
    for name in ["a.pdf.part", ".hidden.pdf", "_private.pdf", "dl.crdownload"]:
        shutil.copy(pdf, root / pid / name)
    shutil.copy(pdf, root / "no-such-pipeline" / "a.pdf")
    shutil.copy(pdf, root / "Not A Slug!" / "a.pdf")
    assert settle(w) == []


def test_symlinks_are_not_followed(setup, tmp_path):
    _, store, root, w = setup
    pid = add(store, "Numbered", ("pdf.page_numbers", {}))
    (root / pid).mkdir()
    secret = tmp_path / "secret.pdf"
    secret.write_bytes(b"%PDF-1.4 secret")
    (root / pid / "link.pdf").symlink_to(secret)
    assert settle(w) == []
    assert secret.exists()


def test_same_name_twice_does_not_overwrite(setup, make_pdf):
    _, store, root, w = setup
    pid = add(store, "Numbered", ("pdf.page_numbers", {}))
    folder = root / pid
    folder.mkdir()
    for _ in range(2):
        shutil.copy(make_pdf("doc.pdf", 1), folder / "doc.pdf")
        settle(w)
    assert len(list((folder / "_done").iterdir())) == 2
    assert len(list((folder / "_out").iterdir())) == 2


def test_background_thread_end_to_end(setup, make_pdf):
    _, store, root, w = setup
    pid = add(store, "Numbered", ("pdf.page_numbers", {}))
    folder = root / pid
    folder.mkdir()
    w.start()
    try:
        shutil.copy(make_pdf("doc.pdf", 1), folder / "doc.pdf")
        deadline = time.time() + 15
        while time.time() < deadline and not (folder / "_done" / "doc.pdf").exists():
            time.sleep(0.05)
        assert (folder / "_done" / "doc.pdf").exists()
    finally:
        w.stop()
    assert not w._thread.is_alive()


def test_workdirs_are_cleaned_up(setup, make_pdf, tmp_path):
    _, store, root, w = setup
    pid = add(store, "Numbered", ("pdf.page_numbers", {}))
    (root / pid).mkdir()
    shutil.copy(make_pdf("doc.pdf", 1), root / pid / "doc.pdf")
    settle(w)
    assert list((tmp_path / "work").iterdir()) == []


def test_server_starts_watcher_from_settings(settings, tmp_path, make_pdf):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings.watch_dir = tmp_path / "inbox"
    settings.watch_interval = 0.05
    with TestClient(create_app(settings)) as c:
        pid = c.post(
            "/api/pipelines",
            json={"name": "Numbered", "steps": [{"tool": "pdf.page_numbers", "params": {}}]},
        ).json()["id"]
        folder = settings.watch_dir / pid
        folder.mkdir()
        shutil.copy(make_pdf("doc.pdf", 1), folder / "doc.pdf")
        deadline = time.time() + 15
        while time.time() < deadline and not (folder / "_done" / "doc.pdf").exists():
            time.sleep(0.05)
        assert (folder / "_done" / "doc.pdf").exists()


def test_cli_pipeline_from_file_and_watch_once(tmp_path, make_pdf):
    spec = tmp_path / "p.json"
    spec.write_text(
        json.dumps({"name": "x", "steps": [{"tool": "pdf.page_numbers", "params": {}}]})
    )
    env = {**os.environ, "TOOLBOX_DATA_DIR": str(tmp_path / "data")}
    out = tmp_path / "out"
    pdf = str(make_pdf("a.pdf", 1))
    r = subprocess.run(
        [sys.executable, "cli.py", "pipeline", str(spec), pdf, "-o", str(out)],
        capture_output=True, text=True, env=env,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert len(list(out.glob("*.pdf"))) == 1

    bad = subprocess.run(
        [sys.executable, "cli.py", "pipeline", "nope", str(make_pdf("b.pdf", 1))],
        capture_output=True, text=True, env=env,
    )  # fmt: skip
    assert bad.returncode == 2
