"""Normalized versioned manuscripts; scientific acceptance stays with the owner."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (
        UniqueConstraint("id", "project_id", "user_id", name="uq_publication_owner"),
        UniqueConstraint("project_id", "user_id", "create_key", name="uq_publication_create_key"),
        ForeignKeyConstraint(
            ["id", "user_id"],
            ["research_entities.id", "research_entities.user_id"],
            name="fk_publication_entity",
        ),
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_publication_project",
        ),
        CheckConstraint("revision>0 AND length(create_sha256)=64", name="ck_publication_revision"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(320))
    create_key: Mapped[str] = mapped_column(String(120))
    create_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PublicationRevision(Base):
    __tablename__ = "publication_revisions"
    __table_args__ = (
        UniqueConstraint(
            "id", "publication_id", "project_id", "user_id", name="uq_publication_revision_owner"
        ),
        UniqueConstraint("publication_id", "revision", name="uq_publication_revision_number"),
        UniqueConstraint("publication_id", "idempotency_key", name="uq_publication_revision_key"),
        ForeignKeyConstraint(
            ["publication_id", "project_id", "user_id"],
            ["publications.id", "publications.project_id", "publications.user_id"],
            name="fk_publication_revision_owner",
        ),
        CheckConstraint(
            "revision>0 AND length(sha256)=64 AND length(source_sha256)=64 AND length(request_sha256)=64",
            name="ck_publication_revision_hash",
        ),
        CheckConstraint(
            "stage IN ('DRAFT','INTERNAL_REVIEW','REVISING','ARCHIVED','SUBMITTED','MAJOR_REVISION','MINOR_REVISION','ACCEPTED','PUBLISHED')",
            name="ck_publication_stage",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    publication_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(320))
    target_venue: Mapped[str] = mapped_column(String(240))
    stage: Mapped[str] = mapped_column(String(24))
    sha256: Mapped[str] = mapped_column(String(64))
    source_sha256: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def revision_fk(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["revision_id", "publication_id", "project_id", "user_id"],
        [
            "publication_revisions.id",
            "publication_revisions.publication_id",
            "publication_revisions.project_id",
            "publication_revisions.user_id",
        ],
        name="fk_publication_" + name + "_revision",
    )


class PublicationChild:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    revision_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    publication_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)


class PublicationSection(PublicationChild, Base):
    __tablename__ = "publication_sections"
    __table_args__ = (
        revision_fk("section"),
        UniqueConstraint(
            "revision_id",
            "key",
            "publication_id",
            "project_id",
            "user_id",
            name="uq_publication_section_owner",
        ),
        UniqueConstraint("revision_id", "position", name="uq_publication_section_position"),
        CheckConstraint(
            "position>=0 AND kind IN ('SKELETON','MANUSCRIPT') AND status IN ('NOT_STARTED','DRAFT','REVISING','COMPLETED')",
            name="ck_publication_section",
        ),
    )
    position: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(240))
    kind: Mapped[str] = mapped_column(String(16))
    markdown: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))


class PublicationSource(PublicationChild, Base):
    __tablename__ = "publication_sources"
    __table_args__ = (
        revision_fk("source"),
        UniqueConstraint(
            "revision_id",
            "bundle_id",
            "publication_id",
            "project_id",
            "user_id",
            name="uq_publication_source_owner",
        ),
        UniqueConstraint("revision_id", "position", name="uq_publication_source_position"),
        ForeignKeyConstraint(
            ["bundle_id", "project_id", "user_id"],
            ["evidence_bundles.id", "evidence_bundles.project_id", "evidence_bundles.user_id"],
            name="fk_publication_source_bundle",
        ),
        ForeignKeyConstraint(
            ["attachment_id", "user_id"],
            ["attachments.id", "attachments.user_id"],
            name="fk_publication_source_attachment",
        ),
        CheckConstraint(
            "position>=0 AND length(expected_bundle_sha256)=64 AND length(snapshot_sha256)=64",
            name="ck_publication_source_hash",
        ),
    )
    position: Mapped[int] = mapped_column(Integer)
    bundle_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    expected_bundle_sha256: Mapped[str] = mapped_column(String(64))
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    preview_sha256: Mapped[str] = mapped_column(String(64))
    attachment_id: Mapped[uuid.UUID] = mapped_column(Uuid)


class PublicationBinding(PublicationChild, Base):
    __tablename__ = "publication_bindings"
    __table_args__ = (
        revision_fk("binding"),
        UniqueConstraint("revision_id", "position", name="uq_publication_binding_position"),
        ForeignKeyConstraint(
            ["revision_id", "section_key", "publication_id", "project_id", "user_id"],
            [
                "publication_sections.revision_id",
                "publication_sections.key",
                "publication_sections.publication_id",
                "publication_sections.project_id",
                "publication_sections.user_id",
            ],
            name="fk_publication_binding_section",
        ),
        ForeignKeyConstraint(
            ["revision_id", "bundle_id", "publication_id", "project_id", "user_id"],
            [
                "publication_sources.revision_id",
                "publication_sources.bundle_id",
                "publication_sources.publication_id",
                "publication_sources.project_id",
                "publication_sources.user_id",
            ],
            name="fk_publication_binding_source",
        ),
        ForeignKeyConstraint(
            ["bundle_id", "claim_revision_id"],
            ["evidence_bundle_claims.bundle_id", "evidence_bundle_claims.revision_id"],
            name="fk_publication_binding_bundle_claim",
        ),
        ForeignKeyConstraint(
            ["claim_revision_id", "claim_id", "project_id", "user_id"],
            [
                "claim_revisions.id",
                "claim_revisions.claim_id",
                "claim_revisions.project_id",
                "claim_revisions.user_id",
            ],
            name="fk_publication_binding_claim",
        ),
        ForeignKeyConstraint(
            ["paper_id", "user_id"],
            ["papers.id", "papers.user_id"],
            name="fk_publication_binding_paper",
        ),
        CheckConstraint(
            "position>=0 AND start_offset>=0 AND end_offset>start_offset AND length(exact_quote)=end_offset-start_offset AND length(expected_claim_sha256)=64",
            name="ck_publication_binding_quote",
        ),
        CheckConstraint(
            "relation IN ('SUPPORTS','REFUTES','CONTEXT') AND format_check IN ('UNCHECKED','OWNER_CONFIRMED','ISSUE') AND metadata_check IN ('UNCHECKED','OWNER_CONFIRMED','ISSUE') AND support_check IN ('UNCHECKED','OWNER_CONFIRMED','ISSUE')",
            name="ck_publication_binding_checks",
        ),
        CheckConstraint(
            "paper_id IS NOT NULL OR (format_check='UNCHECKED' AND metadata_check='UNCHECKED' AND support_check='UNCHECKED')",
            name="ck_publication_citation_identity",
        ),
    )
    position: Mapped[int] = mapped_column(Integer)
    section_key: Mapped[str] = mapped_column(String(64))
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    exact_quote: Mapped[str] = mapped_column(Text)
    bundle_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    claim_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    claim_revision_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    expected_claim_sha256: Mapped[str] = mapped_column(String(64))
    relation: Mapped[str] = mapped_column(String(16))
    paper_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    format_check: Mapped[str] = mapped_column(String(24))
    metadata_check: Mapped[str] = mapped_column(String(24))
    support_check: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(Text)


class PublicationReview(PublicationChild, Base):
    __tablename__ = "publication_reviews"
    __table_args__ = (
        revision_fk("review"),
        UniqueConstraint("publication_id", "idempotency_key", name="uq_publication_review_key"),
        CheckConstraint(
            "decision IN ('ACCEPT','REJECT','COMMENT') AND length(revision_sha256)=64 AND length(request_sha256)=64",
            name="ck_publication_review",
        ),
    )
    revision_sha256: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))
    conclusion: Mapped[str] = mapped_column(Text)
    acknowledge_gaps: Mapped[bool] = mapped_column(Boolean)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_sha256: Mapped[str] = mapped_column(String(64))
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
