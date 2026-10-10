from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, current_context
from app.db import get_db
from app.schemas import SearchPage
from app.services.export_formats import (
    export_bibtex,
    export_csv_zip,
    export_markdown_zip,
    export_ris,
)
from app.services.portability import export_user_data, json_safe
from app.services.search import search_all

router = APIRouter(tags=["portability"])


@router.get("/exports")
def export_data(
    format: Literal["json", "csv", "markdown", "bibtex", "ris"] = "json",
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> Response:
    source = export_user_data(db, context.user)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    if format == "json":
        return JSONResponse(
            json_safe(source),
            headers={"Content-Disposition": f'attachment; filename="researchos-{stamp}.json"'},
        )
    if format == "csv":
        return Response(
            export_csv_zip(source),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="researchos-{stamp}-csv.zip"'},
        )
    if format == "markdown":
        return Response(
            export_markdown_zip(source),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="researchos-{stamp}-markdown.zip"'
            },
        )
    text = export_bibtex(source) if format == "bibtex" else export_ris(source)
    extension = "bib" if format == "bibtex" else "ris"
    return Response(
        text.encode("utf-8"),
        media_type="application/x-bibtex"
        if format == "bibtex"
        else "application/x-research-info-systems",
        headers={"Content-Disposition": f'attachment; filename="researchos-{stamp}.{extension}"'},
    )


@router.get("/search", response_model=SearchPage)
def search(
    q: str = Query(min_length=2, max_length=200),
    types: Annotated[str | None, Query(max_length=120)] = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Annotated[str | None, Query(max_length=256)] = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> SearchPage:
    return search_all(db, context.user.id, q, types=types, limit=limit, cursor=cursor)
