"""Owner-selected immutable document build contracts, never research execution."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas import PageMeta


class BuildFigureSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_id: uuid.UUID
    artifact_id: uuid.UUID
    expected_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    path: str = Field(pattern=r"^figures/[a-z0-9][a-z0-9_-]{0,63}\.(png|jpg|pdf)$")
    caption: str = Field(min_length=1, max_length=4000)


class BuildMetricSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_id: uuid.UUID
    metric_id: uuid.UUID
    expected_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BuildTableSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    title: str = Field(min_length=1, max_length=240)
    metrics: list[BuildMetricSelection] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_metrics(self) -> "BuildTableSelection":
        if len({(m.result_id, m.metric_id) for m in self.metrics}) != len(self.metrics):
            raise ValueError("Select each actual metric once per table")
        return self


class BuildTexOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(
        pattern=r"^(main\.tex|sections/[a-z][a-z0-9_]{0,63}\.tex|bibliography/[a-z][a-z0-9_]{0,63}\.bib)$"
    )
    content: str = Field(max_length=262144)


class BuildSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: uuid.UUID
    expected_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    template_key: str = Field(min_length=1, max_length=80)
    variant: str = Field(min_length=1, max_length=80)
    expected_template_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    font_profile: Literal["ENGLISH", "CJK_COMPAT"] = "ENGLISH"
    private_template_use_approved: bool = False
    submission_id: str = Field(default="", max_length=80, pattern=r"^[A-Za-z0-9_-]*$")
    figures: list[BuildFigureSelection] = Field(default_factory=list, max_length=20)
    tables: list[BuildTableSelection] = Field(default_factory=list, max_length=10)
    tex_overrides: list[BuildTexOverride] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def unique(self) -> "BuildSelection":
        for values in (
            [x.path for x in self.figures],
            [x.key for x in self.tables],
            [x.path for x in self.tex_overrides],
        ):
            if len(set(values)) != len(values):
                raise ValueError("Duplicate build source identity")
        if sum(len(x.content.encode()) for x in self.tex_overrides) > 1048576:
            raise ValueError("TeX overrides exceed 1MiB")
        return self


class BuildFileOut(BaseModel):
    path: str
    sha256: str
    size_bytes: int
    text_content: str | None
    binary: bool


class BuildCompilerOut(BaseModel):
    available: bool
    reason: str
    image_id: str | None
    engine: str
    isolation_contract: str


class BuildTemplateVariant(BaseModel):
    key: str
    options: list[str]
    anonymous: bool
    note: str


class BuildTemplateOut(BaseModel):
    key: str
    family: str
    version: str
    official_url: str
    license: str
    resource_status: str
    variants: list[BuildTemplateVariant]
    manifest_sha256: str
    use_scope: str = "OPEN_TEMPLATE_RESOURCE"
    target_year: int | None = None
    permission_purpose: str = ""


class BuildOptions(BaseModel):
    enabled: bool
    templates: list[BuildTemplateOut]
    compiler: BuildCompilerOut
    font_profiles: list[Literal["ENGLISH", "CJK_COMPAT"]] = ["ENGLISH", "CJK_COMPAT"]


class BuildPreview(BaseModel):
    selection: BuildSelection
    preview_sha256: str
    source_sha256: str
    compile_source_sha256: str
    compiler_manifest_sha256: str
    input_source_zip_sha256: str
    compiler: BuildCompilerOut
    template: BuildTemplateOut
    files: list[BuildFileOut]
    gaps: list[str]
    source_artifact_bytes_included: bool
    scientific_execution_authorized: Literal[False] = False


class BuildCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection: BuildSelection
    expected_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approve_build: Literal[True]
    acknowledge_gaps: bool = False
    idempotency_key: str = Field(min_length=1, max_length=120)


class BuildRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledge_unknown: Literal[True]
    idempotency_key: str = Field(min_length=1, max_length=120)


class BuildCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=120)


class BuildAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: str
    started_at: datetime
    ended_at: datetime | None
    exit_code: int | None
    image_id: str | None
    observations: list[dict[str, Any]]
    error_code: str | None
    source_attachment_id: uuid.UUID | None
    source_zip_sha256: str | None
    source_zip_size_bytes: int | None
    pdf_attachment_id: uuid.UUID | None
    log_attachment_id: uuid.UUID | None
    result_payload: dict[str, Any] | None


class BuildOperationReceipt(BaseModel):
    kind: Literal["create", "cancel", "retry"]
    idempotency_key: str
    request_sha256: str


class BuildSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    publication_id: uuid.UUID
    revision_id: uuid.UUID
    status: Literal[
        "SAVING",
        "QUEUED",
        "RUNNING",
        "CANCEL_REQUESTED",
        "READY",
        "FAILED",
        "NEEDS_ATTENTION",
        "CANCELLED",
    ]
    preview_sha256: str
    source_sha256: str
    compile_source_sha256: str
    compiler_manifest_sha256: str
    input_source_zip_sha256: str
    created_at: datetime


class BuildOut(BuildSummary):
    selection: BuildSelection
    files: list[BuildFileOut]
    gaps: list[str]
    context_current: bool
    source_attachment_id: uuid.UUID | None
    source_zip_sha256: str | None
    source_zip_size_bytes: int | None
    input_source_attachment_id: uuid.UUID | None
    pdf_attachment_id: uuid.UUID | None
    log_attachment_id: uuid.UUID | None
    attempts: list[BuildAttemptOut]
    operation_receipt: BuildOperationReceipt | None = None
    scientific_execution_authorized: Literal[False] = False


class BuildPage(BaseModel):
    items: list[BuildSummary]
    page: PageMeta
