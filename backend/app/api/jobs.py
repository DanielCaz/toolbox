from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response

from app.core.errors import ApiError
from app.core.files import zip_outputs

router = APIRouter(prefix="/api/jobs")


@router.get("/{job_id}")
def job_status(job_id: str, request: Request):
    return request.app.state.jobs.get(job_id).to_dict()


@router.get("/{job_id}/files/{name}")
def download_file(job_id: str, name: str, request: Request):
    jobs = request.app.state.jobs
    jobs.get(job_id)  # 404s for unknown / expired jobs
    out_dir = (jobs.job_dir(job_id) / "out").resolve()
    path = (out_dir / name).resolve()
    if path.parent != out_dir or not path.is_file():
        raise ApiError(404, "not_found", "File not found.")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/{job_id}/zip")
def download_zip(job_id: str, request: Request):
    jobs = request.app.state.jobs
    job = jobs.get(job_id)
    if job.status != "done":
        raise ApiError(409, "not_ready", "The job has not finished.")
    out_dir = jobs.job_dir(job_id) / "out"
    zip_path = zip_outputs(out_dir, jobs.job_dir(job_id) / "outputs.zip")
    return FileResponse(
        zip_path, media_type="application/zip", filename=f"toolbox-{job_id[:8]}.zip"
    )


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    return request.app.state.jobs.cancel(job_id).to_dict()


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: str, request: Request):
    jobs = request.app.state.jobs
    jobs.get(job_id)
    jobs.discard(job_id)
    return Response(status_code=204)
