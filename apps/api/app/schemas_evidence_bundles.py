"""Internal writing bundles; no scientific execution or automatic external transfer."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas import PageMeta


class BundleClaimSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: uuid.UUID
    revision_id: uuid.UUID
    expected_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceBundleSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=240)
    claims: list[BundleClaimSelection] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_claims(self) -> "EvidenceBundleSelection":
        if len({row.claim_id for row in self.claims}) != len(self.claims) or not self.label.strip():
            raise ValueError("Select one exact revision per claim and a nonblank label")
        return self


class EvidenceBundleFileOut(BaseModel):
    path: str
    content: str
    sha256: str
    size_bytes: int


class EvidenceBundlePreview(BaseModel):
    selection: EvidenceBundleSelection
    snapshot_sha256: str
    preview_sha256: str
    bundle_sha256: str
    bundle_size_bytes: int
    files: list[EvidenceBundleFileOut]
    gaps: list[str]
    execution_authorized: Literal[False] = False
    source_artifact_bytes_included: Literal[False] = False


class EvidenceBundleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection: EvidenceBundleSelection
    expected_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approve_bundle: Literal[True]
    acknowledge_gaps: bool = False
    idempotency_key: str = Field(min_length=1, max_length=120)


class EvidenceBundleRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledge_unknown: Literal[True]
    idempotency_key: str = Field(min_length=1, max_length=120)


class EvidenceBundleAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: str
    idempotency_key: str
    error_code: str | None
    attachment_id: uuid.UUID | None
    observations: list[dict[str, Any]]
    started_at: datetime
    ended_at: datetime | None


class EvidenceBundleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    label: str
    status: str
    bundle_sha256: str
    created_at: datetime


class EvidenceBundleOut(EvidenceBundleSummary):
    selection: EvidenceBundleSelection
    snapshot_sha256: str
    preview_sha256: str
    bundle_size_bytes: int
    snapshot: dict[str, Any]
    attachment_id: uuid.UUID | None
    files: list[EvidenceBundleFileOut]
    attempts: list[EvidenceBundleAttemptOut]
    integrity_valid: bool
    context_current: bool
    current_gaps: list[str]
    execution_authorized: Literal[False] = False
    source_artifact_bytes_included: Literal[False] = False


class EvidenceBundlePage(BaseModel):
    items: list[EvidenceBundleSummary]
    page: PageMeta
