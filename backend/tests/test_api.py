import io
import time
import zipfile

from pypdf import PdfReader

from tests.conftest import needs_tesseract


def wait_for(client, job_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.1)
    raise AssertionError("job did not finish in time")


def pdf_upload(path):
    return ("files", (path.name, path.read_bytes(), "application/pdf"))


def test_health_and_catalog(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok" and health["tools"] >= 5

    tools = {t["id"]: t for t in client.get("/api/tools").json()}
    assert {"pdf.merge", "pdf.split", "image.convert", "ocr.pdf", "ocr.image"} <= set(tools)
    assert tools["pdf.split"]["schema"]["properties"]["mode"]["enum"] == [
        "ranges",
        "every_n",
        "each_page",
    ]


def test_merge_end_to_end(client, make_pdf):
    a, b = make_pdf("a.pdf", 2), make_pdf("b.pdf", 1)
    r = client.post(
        "/api/tools/pdf.merge/run",
        files=[pdf_upload(a), pdf_upload(b)],
        data={"params": '{"output_name": "joined.pdf"}'},
    )
    assert r.status_code == 202
    job = wait_for(client, r.json()["job_id"])
    assert job["status"] == "done" and job["progress"] == 1.0
    assert [o["name"] for o in job["outputs"]] == ["joined.pdf"]

    dl = client.get(job["outputs"][0]["url"])
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/pdf"
    assert len(PdfReader(io.BytesIO(dl.content)).pages) == 3


def test_split_zip_download(client, make_pdf):
    src = make_pdf("book.pdf", 4)
    r = client.post(
        "/api/tools/pdf.split/run",
        files=[pdf_upload(src)],
        data={"params": '{"mode": "each_page"}'},
    )
    job = wait_for(client, r.json()["job_id"])
    assert job["status"] == "done" and len(job["outputs"]) == 4

    z = client.get(f"/api/jobs/{job['id']}/zip")
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert len(names) == 4 and names[0] == "book-part-01.pdf"


def test_tool_error_surfaces_as_failed_job(client, make_pdf):
    src = make_pdf("short.pdf", 2)
    r = client.post(
        "/api/tools/pdf.split/run",
        files=[pdf_upload(src)],
        data={"params": '{"mode": "ranges", "ranges": "5-9"}'},
    )
    job = wait_for(client, r.json()["job_id"])
    assert job["status"] == "failed"
    assert job["error"]["code"] == "tool_error"
    assert "outside the document" in job["error"]["message"]


@needs_tesseract
def test_text_tool_returns_text_and_file(client, make_text_image):
    img = make_text_image()
    r = client.post(
        "/api/tools/ocr.image/run", files=[("files", (img.name, img.read_bytes(), "image/png"))]
    )
    job = wait_for(client, r.json()["job_id"])
    assert job["status"] == "done"
    assert "TOOLBOX" in job["text"].upper()
    assert job["outputs"][0]["name"] == "result.txt"


# --- error handling ------------------------------------------------------
def test_unknown_tool_404(client):
    r = client.post("/api/tools/nope.nothing/run")
    assert r.status_code == 404 and r.json()["error"]["code"] == "unknown_tool"


def test_invalid_params_422_and_no_job_left_behind(client, make_pdf, settings):
    src = make_pdf("a.pdf", 2)
    r = client.post(
        "/api/tools/pdf.split/run", files=[pdf_upload(src)], data={"params": '{"mode": "sideways"}'}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert list(settings.jobs_dir.iterdir()) == []


def test_params_must_be_json_object(client, make_pdf):
    src = make_pdf("a.pdf", 1)
    r = client.post("/api/tools/pdf.split/run", files=[pdf_upload(src)], data={"params": "[1]"})
    assert r.status_code == 422


def test_wrong_file_type_415(client, make_text_image):
    img = make_text_image()
    r = client.post(
        "/api/tools/pdf.merge/run",
        files=[
            ("files", (img.name, img.read_bytes(), "application/pdf")),  # lies about its type
            ("files", (img.name, img.read_bytes(), "application/pdf")),
        ],
    )
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_file"


def test_too_few_files_422(client, make_pdf):
    r = client.post("/api/tools/pdf.merge/run", files=[pdf_upload(make_pdf("a.pdf", 1))])
    assert r.status_code == 422


def test_upload_size_limit_413(client):
    big = b"%PDF-1.4\n" + b"0" * (6 * 1024 * 1024)  # limit in fixtures is 5 MB
    r = client.post(
        "/api/tools/pdf.split/run", files=[("files", ("big.pdf", big, "application/pdf"))]
    )
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"


def test_job_not_found_and_path_traversal(client, make_pdf):
    assert client.get("/api/jobs/" + "0" * 32).status_code == 404
    assert client.get("/api/jobs/not-a-valid-id").status_code == 404

    src = make_pdf("a.pdf", 2)
    r = client.post(
        "/api/tools/pdf.split/run",
        files=[pdf_upload(src)],
        data={"params": '{"mode": "each_page"}'},
    )
    job = wait_for(client, r.json()["job_id"])
    for evil in ("..%2Fjob.json", "..%2F..%2Fetc%2Fpasswd", "%2e%2e%2fin%2fa.pdf"):
        assert client.get(f"/api/jobs/{job['id']}/files/{evil}").status_code == 404


def test_delete_job(client, make_pdf):
    src = make_pdf("a.pdf", 2)
    r = client.post(
        "/api/tools/pdf.split/run",
        files=[pdf_upload(src)],
        data={"params": '{"mode": "each_page"}'},
    )
    job = wait_for(client, r.json()["job_id"])
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404


def test_sweeper_removes_expired_jobs(client, make_pdf, settings):
    src = make_pdf("a.pdf", 2)
    r = client.post(
        "/api/tools/pdf.split/run",
        files=[pdf_upload(src)],
        data={"params": '{"mode": "each_page"}'},
    )
    job = wait_for(client, r.json()["job_id"])

    jobs = client.app.state.jobs
    assert jobs.sweep() == 0  # still fresh
    settings.job_ttl_min = -1  # everything is now "expired"
    assert jobs.sweep() == 1
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
