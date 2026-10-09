"""Pipelines: engine, saved presets, and the HTTP API."""

import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.core.errors import ApiError, Cancelled, ToolError
from app.core.pipelines import (
    PipelineDef,
    PipelineStore,
    run_pipeline,
    slugify,
    validate_pipeline,
)
from app.core.registry import Registry
from app.core.tool import ToolContext
from tests.test_api import pdf_upload, wait_for


@pytest.fixture(scope="module")
def registry():
    return Registry()


def defn(*steps, name="Test"):
    return PipelineDef(name=name, steps=[{"tool": t, "params": p} for t, p in steps])


# -- engine -------------------------------------------------------------------
def test_chain_files_into_files(registry, make_pdf, tmp_path):
    # split into single pages, then add page numbers to each, as one pipeline
    d = defn(("pdf.split", {"mode": "each_page"}), ("pdf.page_numbers", {}))
    ctx = ToolContext(workdir=tmp_path / "job")
    result = run_pipeline(registry, d, [make_pdf("in.pdf", 3)], ctx)
    assert len(result.outputs) == 3
    assert all(len(PdfReader(p).pages) == 1 for p in result.outputs)
    assert all(ctx.out_dir in p.parents for p in result.outputs)  # copied to the job output


def test_chain_ends_with_text(registry, make_pdf, tmp_path):
    d = defn(("pdf.rotate", {"degrees": 90}), ("pdf.extract_text", {}))
    result = run_pipeline(registry, d, [make_pdf("in.pdf", 2)], ToolContext(workdir=tmp_path / "j"))
    assert result.text is not None
    assert (Path(result.outputs[0])).name == "result.txt"


def test_chain_across_types(registry, make_image, tmp_path):
    d = defn(
        ("image.resize", {"mode": "width", "width": 100}),
        ("image.to_pdf", {}),
    )
    imgs = [make_image(f"p{i}.png", size=(300, 200)) for i in range(2)]
    result = run_pipeline(registry, d, imgs, ToolContext(workdir=tmp_path / "j"))
    [pdf] = result.outputs
    assert len(PdfReader(pdf).pages) == 2


def test_progress_covers_all_steps(registry, make_pdf, tmp_path):
    seen = []
    ctx = ToolContext(workdir=tmp_path / "j", progress=lambda f, m: seen.append((f, m)))
    run_pipeline(registry, defn(("pdf.rotate", {}), ("pdf.page_numbers", {})), [make_pdf()], ctx)
    assert any("Step 1/2" in m for _, m in seen) and any("Step 2/2" in m for _, m in seen)
    assert all(0 <= f <= 1 for f, _ in seen)


def test_type_mismatch_names_the_step(registry, make_pdf, tmp_path):
    d = defn(("pdf.rotate", {}), ("image.resize", {}))  # rotate gives a PDF; resize wants images
    with pytest.raises(ToolError, match=r"Step 2/2 · .*looks like application/pdf"):
        run_pipeline(registry, d, [make_pdf()], ToolContext(workdir=tmp_path / "j"))


def test_cancel_propagates_to_the_running_step(registry, make_pdf, tmp_path):
    ctx = ToolContext(workdir=tmp_path / "j")
    ctx.cancel()
    with pytest.raises(Cancelled):
        run_pipeline(registry, defn(("pdf.rotate", {})), [make_pdf()], ctx)


def test_child_context_shares_cancellation(tmp_path):
    parent = ToolContext(workdir=tmp_path / "p")
    child = parent.child(tmp_path / "c")
    parent.cancel()
    assert child.cancelled
    assert child._procs is parent._procs


# -- validation ---------------------------------------------------------------
def test_validation_errors_name_the_step(registry):
    with pytest.raises(ApiError, match=r"Step 2: there is no tool 'nope.x'"):
        validate_pipeline(registry, defn(("pdf.rotate", {}), ("nope.x", {})))
    with pytest.raises(ApiError, match=r"Step 1 \(.*\): invalid parameters"):
        validate_pipeline(registry, defn(("pdf.rotate", {"degrees": 45})))
    with pytest.raises(ApiError, match="must be the last step"):
        validate_pipeline(registry, defn(("pdf.extract_text", {}), ("pdf.rotate", {})))


def test_pipeline_def_limits():
    with pytest.raises(ValueError):
        PipelineDef(name="x", steps=[])
    with pytest.raises(ValueError):
        PipelineDef(name="x", steps=[{"tool": "pdf.rotate"}] * 11)


# -- store --------------------------------------------------------------------
def test_slugify():
    assert slugify("Scan → PDF (clean)!") == "scan-pdf-clean"
    assert slugify("Résumé ñ") == "resume-n"
    assert slugify("日本語") == "pipeline"


def test_store_crud_and_unique_slugs(tmp_path):
    store = PipelineStore(tmp_path / "p")
    d = defn(("pdf.rotate", {}), name="Tidy up")
    a, b = store.create(d), store.create(d)
    assert (a, b) == ("tidy-up", "tidy-up-2")
    assert [p["id"] for p in store.list()] == ["tidy-up", "tidy-up-2"]
    store.update(a, defn(("pdf.rotate", {"degrees": 180}), name="Tidy up"))
    assert store.get(a).steps[0].params == {"degrees": 180}
    store.delete(a)
    with pytest.raises(ApiError) as e:
        store.get(a)
    assert e.value.status_code == 404


def test_store_rejects_path_tricks_and_survives_damage(tmp_path):
    store = PipelineStore(tmp_path / "p")
    for bad in ["../secret", "a/b", "..", "A", ""]:
        with pytest.raises(ApiError):
            store.get(bad)
    (tmp_path / "p" / "broken.json").write_text("{not json")
    store.create(defn(("pdf.rotate", {})))
    assert [p["id"] for p in store.list()] == ["test"]  # the damaged file is skipped
    with pytest.raises(ApiError) as e:
        store.get("broken")
    assert e.value.status_code == 500


# -- HTTP API -----------------------------------------------------------------
def body(*steps, name="Rotate then number"):
    return {"name": name, "steps": [{"tool": t, "params": p} for t, p in steps]}


def test_api_crud_and_run(client, make_pdf):
    r = client.post(
        "/api/pipelines", json=body(("pdf.rotate", {"degrees": 90}), ("pdf.page_numbers", {}))
    )
    assert r.status_code == 201 and r.json()["id"] == "rotate-then-number"
    assert client.get("/api/pipelines").json()[0]["name"] == "Rotate then number"

    run = client.post(
        "/api/pipelines/rotate-then-number/run", files=[pdf_upload(make_pdf("a.pdf", 2))]
    )
    assert run.status_code == 202
    job = wait_for(client, run.json()["job_id"])
    assert job["status"] == "done", job
    assert job["tool_id"] == "pipeline:rotate-then-number"
    [out] = job["outputs"]
    content = client.get(out["url"]).content
    assert content.startswith(b"%PDF")

    upd = client.put(
        "/api/pipelines/rotate-then-number", json=body(("pdf.rotate", {}), name="Renamed")
    )
    assert upd.json()["name"] == "Renamed"
    assert client.delete("/api/pipelines/rotate-then-number").status_code == 204
    assert client.get("/api/pipelines/rotate-then-number").status_code == 404


def test_api_rejects_bad_definitions(client):
    r = client.post("/api/pipelines", json=body(("pdf.rotate", {"degrees": 45})))
    assert r.status_code == 422 and "Step 1" in r.json()["error"]["message"]
    assert client.post("/api/pipelines", json={"name": "x", "steps": []}).status_code == 422
    assert client.post("/api/pipelines", json=body(("nope.tool", {}))).status_code == 422


def test_api_adhoc_run_and_fail_fast_on_wrong_first_input(client, make_pdf, make_image):
    steps = json.dumps([{"tool": "pdf.extract_text", "params": {}}])
    ok = client.post(
        "/api/pipelines/run", data={"steps": steps}, files=[pdf_upload(make_pdf("a.pdf", 1))]
    )
    job = wait_for(client, ok.json()["job_id"])
    assert job["status"] == "done" and job["text"] is not None

    img = make_image("x.png")
    bad = client.post(
        "/api/pipelines/run",
        data={"steps": steps},
        files=[("files", ("x.png", img.read_bytes(), "image/png"))],
    )
    assert bad.status_code == 415

    assert client.post("/api/pipelines/run", data={"steps": "nope"}).status_code == 422

    # rejected requests must not leave job folders behind
    jobs_dir = client.app.state.settings.jobs_dir
    before = sorted(d.name for d in jobs_dir.iterdir())
    again = client.post(
        "/api/pipelines/run",
        data={"steps": steps},
        files=[("files", ("x.png", img.read_bytes(), "image/png"))],
    )
    assert again.status_code == 415
    assert sorted(d.name for d in jobs_dir.iterdir()) == before


def test_api_failed_step_is_reported(client, make_pdf):
    steps = json.dumps(
        [
            {"tool": "pdf.rotate", "params": {}},
            {"tool": "pdf.extract_pages", "params": {"pages": "50"}},
        ]
    )
    r = client.post(
        "/api/pipelines/run", data={"steps": steps}, files=[pdf_upload(make_pdf("a.pdf", 1))]
    )
    job = wait_for(client, r.json()["job_id"])
    assert job["status"] == "failed"
    assert job["error"]["code"] == "tool_error"
