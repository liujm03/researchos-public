"""Independent owner classification, separate from immutable reading content."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class NoteProjectClassification(Base):
    __tablename__ = "note_project_classifications"
    __table_args__ = (
        UniqueConstraint("note_id", "user_id", name="uq_note_project_classification_owner"),
        ForeignKeyConstraint(
            ["note_id", "user_id"],
            ["paper_research_notes.id", "paper_research_notes.user_id"],
            ondelete="CASCADE",
            name="fk_note_classification_owner",
        ),
        CheckConstraint("version >= 1", name="ck_note_project_classification_version"),
    )
    note_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NoteProject(Base):
    __tablename__ = "note_projects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["note_id", "user_id"],
            ["note_project_classifications.note_id", "note_project_classifications.user_id"],
            ondelete="CASCADE",
            name="fk_note_project_classification_owner",
        ),
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            ondelete="CASCADE",
            name="fk_note_project_project_owner",
        ),
    )
    note_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, index=True)
