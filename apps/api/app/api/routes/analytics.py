from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, current_context
from app.db import get_db
from app.errors import DomainError
from app.schemas import AnalyticsOverview, DashboardOut, HeatmapOut
from app.services import analytics as service

router = APIRouter(tags=["analytics"])


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    day: date | None = None,
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> DashboardOut:
    local_day = day or datetime.now(ZoneInfo(context.user.timezone)).date()
    return service.dashboard(db, context.user.id, context.user.timezone, local_day)


@router.get("/analytics/overview", response_model=AnalyticsOverview)
def overview(
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> AnalyticsOverview:
    if to_date < from_date or (to_date - from_date).days > 3660:
        raise DomainError("VALIDATION_ERROR", "Invalid analytics date range", 422)
    return service.overview(db, context.user.id, context.user.timezone, from_date, to_date)


@router.get("/analytics/heatmap", response_model=HeatmapOut)
def heatmap(
    year: int = Query(ge=2000, le=2200),
    measure: Literal["hours", "activity"] = "hours",
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> HeatmapOut:
    return service.heatmap(db, context.user.id, context.user.timezone, year, measure)
