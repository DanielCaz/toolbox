from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import jobs as jobs_api
from app.api import pipelines as pipelines_api
from app.api import tools as tools_api
from app.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.jobs import JobManager
from app.core.pipelines import PipelineStore
from app.core.registry import Registry
from app.core.watch import Watcher

log = logging.getLogger("toolbox")
SWEEP_EVERY_SECONDS = 300


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    registry = Registry()
    jobs = JobManager(settings)
    pipelines = PipelineStore(settings.data_dir / "pipelines")

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async def sweeper():
            while True:
                try:
                    removed = await asyncio.to_thread(jobs.sweep)
                    if removed:
                        log.info("Swept %d expired job(s)", removed)
                except Exception:
                    log.exception("Sweeper failed")
                await asyncio.sleep(SWEEP_EVERY_SECONDS)

        task = asyncio.create_task(sweeper())
        watcher = None
        if settings.watch_dir:
            watcher = Watcher(
                registry,
                pipelines,
                settings.watch_dir,
                settings.data_dir / "watch-work",
                settings.watch_interval,
            )
            watcher.start()
            app.state.watcher = watcher
        try:
            yield
        finally:
            task.cancel()
            if watcher:
                await asyncio.to_thread(watcher.stop)
            jobs.shutdown()

    app = FastAPI(
        title="Toolbox",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.registry = registry
    app.state.jobs = jobs
    app.state.pipelines = pipelines

    # -- errors ----------------------------------------------------------
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(exc.to_dict(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        err = ApiError(
            422,
            "validation_error",
            "Invalid request.",
            detail=[{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()],
        )
        return JSONResponse(err.to_dict(), status_code=422)

    # -- API -------------------------------------------------------------
    app.include_router(tools_api.router)
    app.include_router(jobs_api.router)
    app.include_router(pipelines_api.router)

    # -- built frontend (single-port deployment) -------------------------
    static = settings.static_dir
    if (static / "index.html").exists():
        if (static / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")
        static_root = static.resolve()

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith("api/"):
                raise ApiError(404, "not_found", "Not found.")
            candidate = (static_root / full_path).resolve()
            if full_path and candidate.is_file() and static_root in candidate.parents:
                # the service worker and the app shell must revalidate so updates reach users
                fresh = candidate.name in ("sw.js", "manifest.webmanifest")
                return FileResponse(
                    candidate, headers={"Cache-Control": "no-cache"} if fresh else None
                )
            return FileResponse(static_root / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
