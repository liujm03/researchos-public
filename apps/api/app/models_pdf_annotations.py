import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PdfAnnotation(Base):
    __tablename__ = "pdf_annotations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["paper_id", "user_id"], ["research_entities.id", "research_entities.user_id"]
        ),
        ForeignKeyConstraint(
            ["attachment_id", "user_id"], ["attachments.id", "attachments.user_id"]
        ),
        UniqueConstraint("id", "user_id", name="uq_pdf_annotation_owner"),
        CheckConstraint(
            "kind IN ('HIGHLIGHT','UNDERLINE','COMMENT','INK')", name="ck_pdf_annotation_kind"
        ),
        CheckConstraint("page >= 1 AND page <= 2000", name="ck_pdf_annotation_page"),
        CheckConstraint("revision >= 1", name="ck_pdf_annotation_revision"),
        Index("ix_pdf_annotation_source", "user_id", "paper_id", "attachment_id", "source_sha256"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("papers.id"))
    attachment_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_sha256: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    page: Mapped[int] = mapped_column(Integer)
    color: Mapped[str] = mapped_column(String(7))
    body: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    last_expected_revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PdfAnnotationGeometry(Base):
    __tablename__ = "pdf_annotation_geometries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["annotation_id", "user_id"], ["pdf_annotations.id", "pdf_annotations.user_id"]
        ),
        UniqueConstraint("annotation_id", "position", name="uq_pdf_geometry_position"),
        UniqueConstraint("id", "user_id", name="uq_pdf_geometry_owner"),
        CheckConstraint("geometry_kind IN ('RECT','STROKE')", name="ck_pdf_geometry_kind"),
        CheckConstraint("position >= 0 AND position < 50", name="ck_pdf_geometry_position"),
        CheckConstraint(
            "(geometry_kind='STROKE' AND x IS NULL AND y IS NULL AND width IS NULL AND height IS NULL) OR (geometry_kind='RECT' AND x IS NOT NULL AND y IS NOT NULL AND width IS NOT NULL AND height IS NOT NULL AND x>=0 AND y>=0 AND width>0 AND height>0 AND x+width<=1.000001 AND y+height<=1.000001)",
            name="ck_pdf_geometry_bounds",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    annotation_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    position: Mapped[int] = mapped_column(Integer)
    geometry_kind: Mapped[str] = mapped_column(String(8))
    x: Mapped[float | None] = mapped_column(Float)
    y: Mapped[float | None] = mapped_column(Float)
    width: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)


class PdfAnnotationPoint(Base):
    __tablename__ = "pdf_annotation_points"
    __table_args__ = (
        ForeignKeyConstraint(
            ["geometry_id", "user_id"],
            ["pdf_annotation_geometries.id", "pdf_annotation_geometries.user_id"],
        ),
        UniqueConstraint("geometry_id", "position", name="uq_pdf_point_position"),
        CheckConstraint("position >= 0 AND position < 2000", name="ck_pdf_point_position"),
        CheckConstraint("x>=0 AND x<=1 AND y>=0 AND y<=1", name="ck_pdf_point_bounds"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    geometry_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    position: Mapped[int] = mapped_column(Integer)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
