from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.api.tools import _save_uploads
from app.core.errors import ApiError
from app.core.files import check_inputs
from app.core.pipelines import PipelineDef, run_pipeline, validate_pipeline

router = APIRouter(prefix="/api/pipelines")


@router.get("")
def list_pipelines(request: Request):
    return request.app.state.pipelines.list()


@router.post("", status_code=201)
def create_pipeline(definition: PipelineDef, request: Request):
    # Saving does not require the tools to be installed *right now* (the preset may be shared
    # between machines), but it does require every tool id and parameter to be valid.
    validate_pipeline(request.app.state.registry, definition, check_available=False)
    pid = request.app.state.pipelines.create(definition)
    return {"id": pid, **definition.model_dump()}


@router.get("/{pid}")
def get_pipeline(pid: str, request: Request):
    return {"id": pid, **request.app.state.pipelines.get(pid).model_dump()}


@router.put("/{pid}")
def update_pipeline(pid: str, definition: PipelineDef, request: Request):
    validate_pipeline(request.app.state.registry, definition, check_available=False)
    request.app.state.pipelines.update(pid, definition)
    return {"id": pid, **definition.model_dump()}


@router.delete("/{pid}", status_code=204)
def delete_pipeline(pid: str, request: Request):
    request.app.state.pipelines.delete(pid)


async def _start(
    request: Request, definition: PipelineDef, files: list[UploadFile], label: str
) -> dict:
    registry = request.app.state.registry
    jobs = request.app.state.jobs
    validate_pipeline(registry, definition)

    job_id, job_dir = jobs.allocate()
    try:
        paths = await _save_uploads(
            files, job_dir / "in", request.app.state.settings.max_upload_bytes
        )
        check_inputs(registry.get(definition.steps[0].tool), paths)  # fail fast on step 1
    except Exception:
        jobs.discard(job_id)
        raise

    def runner(ctx):
        return run_pipeline(registry, definition, paths, ctx)

    jobs.submit(job_id, label, runner)
    return {"job_id": job_id}


@router.post("/run", status_code=202)
async def run_adhoc(
    request: Request, files: list[UploadFile] = File(default=[]), steps: str = Form(...)
):
    """Run an unsaved pipeline: ``steps`` is a JSON list of {tool, params}."""
    try:
        raw = json.loads(steps)
        definition = PipelineDef(name="Ad-hoc pipeline", steps=raw)
    except (ValueError, TypeError):
        raise ApiError(
            422, "validation_error", "'steps' must be a JSON list of {tool, params}."
        ) from None
    except Exception as e:  # pydantic ValidationError
        raise ApiError(422, "validation_error", f"Invalid steps: {e}") from None
    return await _start(request, definition, files, "pipeline")


@router.post("/{pid}/run", status_code=202)
async def run_saved(pid: str, request: Request, files: list[UploadFile] = File(default=[])):
    definition = request.app.state.pipelines.get(pid)
    return await _start(request, definition, files, f"pipeline:{pid}")
