import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.core.config import get_settings
from app.db import get_db
from app.domain.storage import StorageProvider
from app.errors import DomainError
from app.providers.pdf_annotations.pypdf_adapter import PypdfAnnotationProvider
from app.providers.registry import storage_provider
from app.schemas_pdf_annotations import PdfAnnotationOut, PdfAnnotationPut, PdfAnnotationsOut
from app.services import pdf_annotations as service


def annotations_enabled(context: AuthContext = Depends(current_context)) -> None:
    if not get_settings().pdf_annotations_enabled:
        raise DomainError("PDF_ANNOTATIONS_DISABLED", "PDF批注正在软件验收；现有原文阅读不受影响。", 503)


router = APIRouter(tags=["pdf-annotations"], dependencies=[Depends(annotations_enabled)])
BASE = "/papers/{paper_id}/attachments/{attachment_id}"


def _storage(
    db: Session, context: AuthContext, paper_id: uuid.UUID, attachment_id: uuid.UUID
) -> StorageProvider:
    source = service.source_attachment(db, context.user.id, paper_id, attachment_id)
    return storage_provider(source.storage_provider)


@router.get(BASE + "/annotations", response_model=PdfAnnotationsOut)
async def list_marks(
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PdfAnnotationsOut:
    return await service.list_annotations(
        db,
        context.user.id,
        paper_id,
        attachment_id,
        _storage(db, context, paper_id, attachment_id),
        PypdfAnnotationProvider(),
    )


@router.get(BASE + "/annotations/{annotation_id}", response_model=PdfAnnotationOut)
def get_mark(
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    annotation_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> PdfAnnotationOut:
    return service.get_annotation(db, context.user.id, paper_id, attachment_id, annotation_id)


@router.put(BASE + "/annotations/{annotation_id}", response_model=PdfAnnotationOut)
async def put_mark(
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    annotation_id: uuid.UUID,
    data: PdfAnnotationPut,
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PdfAnnotationOut:
    return await service.put_annotation(
        db,
        context.user.id,
        paper_id,
        attachment_id,
        annotation_id,
        data,
        _storage(db, context, paper_id, attachment_id),
        PypdfAnnotationProvider(),
    )


@router.delete(BASE + "/annotations/{annotation_id}", response_model=PdfAnnotationOut)
def delete_mark(
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    annotation_id: uuid.UUID,
    expected_revision: int = Query(ge=1),
    source_sha256: str = Query(pattern=r"^[a-f0-9]{64}$"),
    context: AuthContext = Depends(csrf_context),
    db: Session = Depends(get_db),
) -> PdfAnnotationOut:
    return service.delete_annotation(
        db,
        context.user.id,
        paper_id,
        attachment_id,
        annotation_id,
        expected_revision,
        source_sha256,
    )


@router.get(
    BASE + "/annotated-pdf",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
async def download_annotated_pdf(
    paper_id: uuid.UUID,
    attachment_id: uuid.UUID,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> Response:
    content = await service.export_annotated_pdf(
        db,
        context.user.id,
        paper_id,
        attachment_id,
        _storage(db, context, paper_id, attachment_id),
        PypdfAnnotationProvider(),
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="annotated-{attachment_id}.pdf"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
