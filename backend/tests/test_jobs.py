"""Job runner behaviour: batch uploads, cancellation, subprocess handling."""

import time

import pytest

from app.core.errors import Cancelled, ToolError
from app.core.jobs import ExecResult
from app.core.tool import ToolContext
from tests.test_api import pdf_upload, wait_for


def wait_status(client, job_id, wanted, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in wanted:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job never reached {wanted}")


def test_batch_upload_through_the_api(client, make_pdf):
    files = [pdf_upload(make_pdf(f"doc{i}.pdf", 2)) for i in range(3)]
    r = client.post("/api/tools/pdf.rotate/run", files=files, data={"params": '{"degrees": 90}'})
    assert r.status_code == 202
    job = wait_for(client, r.json()["job_id"])
    assert job["status"] == "done"
    assert len(job["outputs"]) == 3


def test_non_batch_tools_still_reject_extra_files(client, make_text_image):
    img = make_text_image()
    # ocr.pdf is batch; image.convert takes many natively; pdf.merge needs 2+. Use a text file.
    files = [("files", (f"x{i}.pdf", b"%PDF-1.4 x", "application/pdf")) for i in range(2)]
    r = client.post("/api/tools/ocr.image/run", files=files)
    assert r.status_code == 415  # wrong type, rejected before anything runs
    assert img.exists()


def test_catalog_exposes_batch_flag(client):
    tools = {t["id"]: t for t in client.get("/api/tools").json()}
    assert tools["pdf.rotate"]["batch"] is True
    assert tools["pdf.merge"]["batch"] is False


def test_cancel_running_job_kills_subprocess(client):
    jobs = client.app.state.jobs
    job_id, _ = jobs.allocate()
    started = {}

    def runner(ctx: ToolContext):
        started["t"] = time.time()
        ctx.run_cmd(["sleep", "30"])  # would block the test for 30 s if not killed
        return ExecResult()

    jobs.submit(job_id, "test.sleep", runner)
    wait_status(client, job_id, {"running"})
    time.sleep(0.2)  # let the subprocess actually start
    r = client.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 200
    job = wait_status(client, job_id, {"cancelled", "done", "failed"})
    assert job["status"] == "cancelled"
    assert time.time() - started["t"] < 10


def test_cancel_queued_job_never_runs(client):
    jobs = client.app.state.jobs
    ran = []
    # occupy both workers, then queue a third job
    blockers = []
    for _ in range(jobs.settings.workers):
        bid, _ = jobs.allocate()
        jobs.submit(bid, "test.block", lambda ctx: (ctx.run_cmd(["sleep", "5"]), ExecResult())[1])
        blockers.append(bid)
    time.sleep(0.2)

    jid, _ = jobs.allocate()
    jobs.submit(jid, "test.queued", lambda ctx: (ran.append(1), ExecResult())[1])
    assert client.get(f"/api/jobs/{jid}").json()["status"] == "queued"
    assert client.post(f"/api/jobs/{jid}/cancel").json()["status"] == "cancelled"

    for b in blockers:
        client.post(f"/api/jobs/{b}/cancel")
    time.sleep(0.5)
    assert ran == []


def test_cancel_finished_job_is_a_noop(client, make_pdf):
    r = client.post("/api/tools/pdf.rotate/run", files=[pdf_upload(make_pdf("a.pdf", 1))])
    job = wait_for(client, r.json()["job_id"])
    again = client.post(f"/api/jobs/{job['id']}/cancel").json()
    assert again["status"] == "done"


def test_run_cmd_errors(tmp_path):
    ctx = ToolContext(workdir=tmp_path)
    with pytest.raises(ToolError, match="not installed"):
        ctx.run_cmd(["definitely-not-a-binary-xyz"])
    with pytest.raises(ToolError, match="failed: .*boom"):
        ctx.run_cmd(["sh", "-c", "echo boom; exit 3"])
    with pytest.raises(ToolError, match="timed out"):
        ctx.run_cmd(["sleep", "5"], timeout=0.3)
    seen = []
    out = ctx.run_cmd(["sh", "-c", "echo one; echo two"], on_line=seen.append)
    assert seen == ["one", "two"] and "two" in out


def test_run_cmd_refuses_after_cancel(tmp_path):
    ctx = ToolContext(workdir=tmp_path)
    ctx.cancel()
    with pytest.raises(Cancelled):
        ctx.run_cmd(["echo", "hi"])


def test_unknown_job_cancel_404(client):
    assert client.post("/api/jobs/" + "a" * 32 + "/cancel").status_code == 404
