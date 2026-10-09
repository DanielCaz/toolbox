from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.core.errors import ApiError
from app.core.files import check_inputs, dedupe_name, safe_name
from app.core.jobs import validate_params

router = APIRouter(prefix="/api")


@router.get("/health")
def health(request: Request):
    registry = request.app.state.registry
    return {"status": "ok", "tools": len(registry.tools), "missing": registry.missing_binaries()}


@router.get("/tools")
def list_tools(request: Request):
    return request.app.state.registry.catalog()


async def _save_uploads(files: list[UploadFile], dest: Path, max_bytes: int) -> list[Path]:
    saved: list[Path] = []
    total = 0
    for up in files:
        name = dedupe_name(dest, safe_name(up.filename))
        path = dest / name
        with path.open("wb") as fh:
            while chunk := await up.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ApiError(
                        413,
                        "too_large",
                        f"Upload exceeds the {max_bytes // (1024 * 1024)} MB limit.",
                    )
                fh.write(chunk)
        saved.append(path)
    return saved


@router.post("/tools/{tool_id}/run", status_code=202)
async def run_tool(
    tool_id: str,
    request: Request,
    files: list[UploadFile] = File(default=[]),
    params: str = Form("{}"),
):
    registry = request.app.state.registry
    jobs = request.app.state.jobs
    settings = request.app.state.settings

    tool = registry.get(tool_id)
    missing = registry.missing(tool)
    if missing:
        raise ApiError(
            503, "tool_unavailable", f"{tool.name} is unavailable: missing {', '.join(missing)}."
        )

    try:
        raw = json.loads(params or "{}")
        if not isinstance(raw, dict):
            raise ValueError
    except ValueError:
        raise ApiError(422, "validation_error", "'params' must be a JSON object.") from None

    job_id, job_dir = jobs.allocate()
    try:
        paths = await _save_uploads(files, job_dir / "in", settings.max_upload_bytes)
        check_inputs(tool, paths)
        params_obj = validate_params(tool, raw)
    except Exception:
        jobs.discard(job_id)
        raise

    jobs.submit_tool(job_id, tool, paths, params_obj)
    return {"job_id": job_id}
