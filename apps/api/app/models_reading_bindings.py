"""Owner-approved snapshots of files actually loaded by original PDF reading."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PaperReadingSkillFile(Base):
    __tablename__ = "paper_reading_skill_files"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plan_id", "user_id"],
            ["paper_reading_approval_plans.id", "paper_reading_approval_plans.user_id"],
            name="fk_reading_skill_file_plan_owner",
        ),
        CheckConstraint("length(file_key_sha256) = 64", name="ck_reading_skill_file_key"),
        CheckConstraint("length(path) BETWEEN 1 AND 2000", name="ck_reading_skill_file_path"),
        CheckConstraint("role IN ('INSTRUCTION','TEMPLATE')", name="ck_reading_skill_file_role"),
        CheckConstraint("length(sha256) = 64", name="ck_reading_skill_file_hash"),
        CheckConstraint("size_bytes BETWEEN 0 AND 256000", name="ck_reading_skill_file_size"),
        CheckConstraint("length(content) <= 256000", name="ck_reading_skill_file_content"),
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    file_key_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(24))
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
