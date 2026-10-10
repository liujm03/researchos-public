"""Authenticated public-source metadata review and owner confirmation."""

import uuid
from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.db import get_db
from app.domain import repository_imports as schema
from app.providers.registry import repository_provider_catalog
from app.services import repository_imports as service

router = APIRouter(tags=["repository-imports"])


@router.get("/repository-providers", response_model=schema.RepositoryProviderCatalogOut)
def providers(
    context: AuthContext = Depends(current_context),
) -> schema.RepositoryProviderCatalogOut:
    return schema.RepositoryProviderCatalogOut(
        items=[
            schema.RepositoryProviderOut.model_validate(asdict(item))
            for item in repository_provider_catalog()
        ]
    )


@router.post(
    "/repository-imports/preview", response_model=schema.RepositoryImportOut, status_code=201
)
async def preview(
    body: schema.RepositoryPreviewRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.RepositoryImportOut:
    record = await service.create_preview(db, context.user.id, body)
    return service.preview_out(db, context.user.id, record)


@router.get("/repository-imports", response_model=schema.RepositoryImportPage)
def history(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.RepositoryImportPage:
    return service.list_previews(db, context.user.id, limit, offset)


@router.get("/repository-imports/{preview_id}", response_model=schema.RepositoryImportOut)
def detail(
    preview_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.RepositoryImportOut:
    return service.preview_out(
        db, context.user.id, service.get_preview(db, context.user.id, preview_id)
    )


@router.post("/repository-imports/{preview_id}/confirm", response_model=schema.RepositoryImportOut)
def confirm(
    preview_id: uuid.UUID,
    body: schema.RepositoryConfirmRequest,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> schema.RepositoryImportOut:
    return service.preview_out(
        db, context.user.id, service.confirm_preview(db, context.user.id, preview_id, body)
    )


@router.get("/repository-sources/{source_id}", response_model=schema.RepositorySourceOut)
def source(
    source_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> schema.RepositorySourceOut:
    return service.source_out(db, context.user.id, source_id)
