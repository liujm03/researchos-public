import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routes import (
    analysis,
    analytics,
    arxiv_import,
    attachments,
    auth,
    baseline_runs,
    baselines,
    bibliography_import,
    claims,
    code_changes,
    codex,
    doi_import,
    evidence_bundles,
    experiment_artifact_upload,
    experiment_registries,
    experiments,
    ideas,
    literature_classification,
    literature_ingest,
    literature_providers,
    literature_recommendations,
    manuscript_builds,
    note_deletion,
    note_trash,
    paper_reproduction,
    papers,
    pdf_annotations,
    pdf_reading,
    planning_brief_proposals,
    portability,
    productivity,
    project_archives,
    project_sources,
    projects,
    provisioning,
    publications,
    reference_manager,
    repository_assets,
    repository_imports,
    research_briefs,
    research_planning,
    server_results,
    server_task_packages,
    system,
    writing,
    zotero_sync,
)
from app.core.config import get_settings
from app.db import engine
from app.errors import DomainError
from app.services.configuration import ensure_production_ready

settings = get_settings()
ensure_production_ready(settings)
app = FastAPI(
    title="ResearchOS API",
    version="0.1.0",
    openapi_url=None if settings.app_env == "production" else "/api/v1/openapi.json",
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None if settings.app_env == "production" else "/redoc",
)


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "request_id": request.state.request_id,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": [
                    {key: item[key] for key in ("loc", "msg", "type") if key in item}
                    for item in exc.errors()
                ],
                "request_id": request.state.request_id,
            }
        },
    )


@app.middleware("http")
async def request_id_middleware(request: Request, call_next: object) -> object:
    request.state.request_id = str(uuid.uuid4())
    response = await call_next(request)  # type: ignore[operator]
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}


app.include_router(auth.router, prefix="/api/v1")
app.include_router(auth.me_router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")

app.include_router(ideas.router, prefix="/api/v1")
app.include_router(claims.router, prefix="/api/v1")
app.include_router(research_briefs.router, prefix="/api/v1")
app.include_router(research_planning.router, prefix="/api/v1")
app.include_router(server_task_packages.router, prefix="/api/v1")
app.include_router(server_results.router, prefix="/api/v1")
app.include_router(code_changes.router, prefix="/api/v1")
app.include_router(planning_brief_proposals.router, prefix="/api/v1")
app.include_router(project_archives.router, prefix="/api/v1")
app.include_router(provisioning.router, prefix="/api/v1")
app.include_router(projects.related_router, prefix="/api/v1")
app.include_router(papers.router, prefix="/api/v1")
app.include_router(pdf_annotations.router, prefix="/api/v1")
app.include_router(papers.notes_router, prefix="/api/v1")
app.include_router(productivity.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(portability.router, prefix="/api/v1")
app.include_router(reference_manager.router, prefix="/api/v1")
app.include_router(repository_imports.router, prefix="/api/v1")
app.include_router(repository_assets.router, prefix="/api/v1")
app.include_router(project_sources.router, prefix="/api/v1")
app.include_router(baselines.router, prefix="/api/v1")
app.include_router(baseline_runs.router, prefix="/api/v1")
app.include_router(attachments.router, prefix="/api/v1")
app.include_router(analysis.router, prefix="/api/v1")
app.include_router(zotero_sync.router, prefix="/api/v1")
app.include_router(literature_ingest.router, prefix="/api/v1")
app.include_router(codex.router, prefix="/api/v1")
app.include_router(paper_reproduction.router, prefix="/api/v1")
app.include_router(pdf_reading.router, prefix="/api/v1")
app.include_router(experiment_registries.router, prefix="/api/v1")
app.include_router(experiments.router, prefix="/api/v1")
app.include_router(experiment_artifact_upload.router, prefix="/api/v1")
app.include_router(bibliography_import.router, prefix="/api/v1")
app.include_router(doi_import.router, prefix="/api/v1")
app.include_router(arxiv_import.router, prefix="/api/v1")
app.include_router(literature_providers.router, prefix="/api/v1")
app.include_router(literature_recommendations.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")
app.include_router(evidence_bundles.router, prefix="/api/v1")
app.include_router(publications.router, prefix="/api/v1")
app.include_router(writing.router, prefix="/api/v1")
app.include_router(manuscript_builds.router, prefix="/api/v1")
app.include_router(note_trash.router, prefix="/api/v1")
app.include_router(note_deletion.router, prefix="/api/v1")
app.include_router(literature_classification.router, prefix="/api/v1")
