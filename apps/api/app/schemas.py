import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas_dashboard import DashboardVisualization
from app.schemas_literature_context import PaperLiteratureContextOut
from app.schemas_venue_ratings import VenueAssessmentOut

ProjectStatus = Literal["active", "on_hold", "completed", "archived"]
PipelineStage = Literal[
    "idea",
    "literature_review",
    "problem_definition",
    "baseline",
    "method",
    "experiment",
    "ablation",
    "writing",
    "submission",
    "revision",
    "accepted",
]
ReadingStatus = Literal[
    "unread", "skimming", "reading", "deep_reading", "reproducing", "completed", "archived"
]
TaskCategory = Literal[
    "reading",
    "learning",
    "coding",
    "experiment",
    "dataset",
    "writing",
    "meeting",
    "research",
    "other",
]
TaskStatus = Literal["todo", "in_progress", "blocked", "done", "cancelled"]
TaskPriority = Literal["low", "medium", "high", "urgent"]


class PageMeta(BaseModel):
    limit: int
    next_cursor: str | None
    total: int | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    parent_project_id: uuid.UUID | None = None
    summary: str | None = None
    problem: str | None = None
    motivation: str | None = None
    research_gap: str | None = None
    method_overview: str | None = None
    status: ProjectStatus = "active"
    pipeline_stage: PipelineStage = "idea"
    started_on: date | None = None
    target_on: date | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    parent_project_id: uuid.UUID | None = None
    summary: str | None = None
    problem: str | None = None
    motivation: str | None = None
    research_gap: str | None = None
    method_overview: str | None = None
    status: ProjectStatus | None = None
    pipeline_stage: PipelineStage | None = None
    started_on: date | None = None
    target_on: date | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    parent_project_id: uuid.UUID | None
    summary: str | None
    problem: str | None
    motivation: str | None
    research_gap: str | None
    method_overview: str | None
    status: ProjectStatus
    pipeline_stage: PipelineStage
    started_on: date | None
    target_on: date | None
    version: int
    created_at: datetime
    updated_at: datetime


class ProjectPage(BaseModel):
    items: list[ProjectOut]
    page: PageMeta


class QuestionCreate(BaseModel):
    question: str = Field(min_length=1)
    rationale: str | None = None
    parent_question_id: uuid.UUID | None = None
    sort_order: int = 0


class QuestionPatch(BaseModel):
    question: str | None = Field(default=None, min_length=1)
    rationale: str | None = None
    status: Literal["open", "investigating", "answered", "archived"] | None = None
    sort_order: int | None = None


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    question: str
    rationale: str | None
    parent_question_id: uuid.UUID | None
    status: str
    sort_order: int


class MilestoneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str | None = None
    due_on: date | None = None
    sort_order: int = 0


class MilestonePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    due_on: date | None = None
    status: Literal["planned", "in_progress", "completed", "cancelled"] | None = None
    sort_order: int | None = None


class MilestoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str | None
    due_on: date | None
    completed_at: datetime | None
    status: str
    sort_order: int


class ProjectPaperSummary(BaseModel):
    id: uuid.UUID
    title: str
    year: int | None
    role: str


class PaperCreate(BaseModel):
    title: str = Field(min_length=1, max_length=600)
    year: int | None = Field(default=None, ge=1400, le=2200)
    venue_name: str | None = Field(default=None, max_length=320)
    venue_type: Literal["journal", "conference", "preprint", "other"] = "other"
    authors: list[str] = Field(default_factory=list)
    doi: str | None = None
    arxiv_id: str | None = None
    abstract: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    project_ids: list[uuid.UUID] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class PaperPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=600)
    year: int | None = Field(default=None, ge=1400, le=2200)
    doi: str | None = None
    arxiv_id: str | None = None
    abstract: str | None = None
    url: str | None = None
    pdf_url: str | None = None


class ReadingUpdate(BaseModel):
    status: ReadingStatus
    importance: int | None = Field(default=None, ge=1, le=5)
    relevance: int | None = Field(default=None, ge=0, le=100)


class ReadingOut(BaseModel):
    status: ReadingStatus
    importance: int | None
    relevance: int | None
    last_read_at: datetime | None
    completed_at: datetime | None


class VenueOut(BaseModel):
    id: uuid.UUID
    name: str
    type: str


class AuthorOut(BaseModel):
    id: uuid.UUID
    display_name: str
    position: int


class PaperSourceOut(BaseModel):
    provider_key: str
    provider_id: str
    source_version: int | None
    source_url: str | None
    fetched_at: datetime


class PaperOut(BaseModel):
    id: uuid.UUID
    title: str
    year: int | None
    venue: VenueOut | None
    venue_assessments: list[VenueAssessmentOut] = Field(default_factory=list)
    authors: list[AuthorOut]
    doi: str | None
    arxiv_id: str | None
    abstract: str | None
    url: str | None
    pdf_url: str | None
    reading: ReadingOut
    tags: list[str]
    project_ids: list[uuid.UUID]
    literature_context: PaperLiteratureContextOut = Field(default_factory=PaperLiteratureContextOut)
    sources: list[PaperSourceOut]
    version: int
    created_at: datetime
    updated_at: datetime


class PaperPage(BaseModel):
    items: list[PaperOut]
    page: PageMeta


class NoteCreate(BaseModel):
    title: str | None = None
    body_markdown: str = Field(min_length=1)
    note_type: str = "general"
    source_locator: str | None = None


class NotePatch(BaseModel):
    title: str | None = None
    body_markdown: str | None = Field(default=None, min_length=1)
    note_type: str | None = None
    source_locator: str | None = None


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    paper_id: uuid.UUID
    title: str | None
    body_markdown: str
    note_type: str
    source_locator: str | None
    is_ai_draft: bool
    version: int
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=320)
    description: str | None = None
    project_id: uuid.UUID | None = None
    parent_task_id: uuid.UUID | None = None
    category: TaskCategory = "research"
    priority: TaskPriority = "medium"
    status: TaskStatus = "todo"
    due_at: datetime | None = None
    estimated_minutes: int | None = Field(default=None, ge=0)


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=320)
    description: str | None = None
    project_id: uuid.UUID | None = None
    parent_task_id: uuid.UUID | None = None
    category: TaskCategory | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    due_at: datetime | None = None
    estimated_minutes: int | None = Field(default=None, ge=0)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    project_id: uuid.UUID | None
    parent_task_id: uuid.UUID | None
    category: TaskCategory
    priority: TaskPriority
    status: TaskStatus
    due_at: datetime | None
    estimated_minutes: int | None
    actual_minutes: int | None
    completed_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class TaskPage(BaseModel):
    items: list[TaskOut]
    page: PageMeta


class JournalUpdate(BaseModel):
    completed: str | None = None
    papers_read: str | None = None
    experiments: str | None = None
    learning: str | None = None
    problems: str | None = None
    new_ideas: str | None = None
    tomorrow_plan: str | None = None


class JournalOut(JournalUpdate):
    model_config = ConfigDict(from_attributes=True)

    journal_date: date
    version: int
    updated_at: datetime


class TimeEntryCreate(BaseModel):
    project_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    category: TaskCategory
    started_at: datetime
    ended_at: datetime
    note: str | None = None


class TimeEntryOut(TimeEntryCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID


class DashboardTask(BaseModel):
    id: uuid.UUID
    title: str
    category: str
    status: str
    due_at: datetime | None
    project_id: uuid.UUID | None


class DashboardPaper(BaseModel):
    id: uuid.UUID
    title: str
    year: int | None
    reading_status: str
    importance: int | None
    relevance: int | None
    last_read_at: datetime | None


class DashboardProject(BaseModel):
    id: uuid.UUID
    name: str
    pipeline_stage: str
    status: str


class DashboardOut(BaseModel):
    date: date
    timezone: str
    today_tasks: list[DashboardTask]
    current_projects: list[DashboardProject]
    recent_papers: list[DashboardPaper]
    papers_read_total: int
    research_minutes_week: int
    research_minutes_month: int
    tasks_completed: int
    tasks_open: int
    experiments_available: bool = False
    publications_available: bool = False
    visualization: DashboardVisualization | None = None


class AnalyticsOverview(BaseModel):
    from_date: date
    to_date: date
    research_minutes_by_category: dict[str, int]
    papers_completed: int
    tasks_completed: int
    projects_active: int


class HeatmapDay(BaseModel):
    date: date
    value: float
    level: int


class HeatmapOut(BaseModel):
    year: int
    measure: Literal["hours", "activity"]
    unit: str
    days: list[HeatmapDay]


class SearchHit(BaseModel):
    type: Literal["paper", "project", "task", "note", "codex_task", "idea", "claim"]
    entity_id: uuid.UUID
    title: str
    href: str
    snippet: str | None = None
    matched_fields: list[str] = Field(default_factory=list)


class SearchPage(BaseModel):
    items: list[SearchHit]
    page: PageMeta
