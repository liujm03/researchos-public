from datetime import date, datetime

from pydantic import BaseModel


class DashboardActivityDay(BaseModel):
    date: date
    papers_added: int
    tasks_completed: int


class DashboardVisualization(BaseModel):
    observed_at: datetime
    from_date: date
    to_date: date
    papers_total: int
    papers_with_notes: int
    projects_active: int
    ideas_total: int
    tasks_open: int
    tasks_completed: int
    ai_active: int
    ai_attention: int
    reading_status_counts: dict[str, int]
    project_stage_counts: dict[str, int]
    ai_status_counts: dict[str, int]
    activity: list[DashboardActivityDay]
