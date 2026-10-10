import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class VenueAssessment(Base):
    __tablename__ = "venue_assessments"
    __table_args__ = (
        UniqueConstraint("user_id", "request_key", name="uq_venue_assessment_request"),
        CheckConstraint(
            "scheme IN ('JCR','CAS','CCF','INDEX','TOP_CONFERENCE')",
            name="ck_venue_assessment_scheme",
        ),
        CheckConstraint(
            "metric_year >= 1900 AND metric_year <= 2200", name="ck_venue_assessment_year"
        ),
        CheckConstraint(
            "impact_factor IS NULL OR (scheme = 'JCR' AND impact_factor >= 0 AND impact_factor <= 1000)",
            name="ck_venue_assessment_jif",
        ),
        CheckConstraint("source_kind = 'OWNER_REPORTED'", name="ck_venue_assessment_source"),
        CheckConstraint(
            "(scheme='JCR' AND (rank_value IS NULL OR rank_value IN ('Q1','Q2','Q3','Q4'))) OR (scheme='CAS' AND rank_value IS NOT NULL AND rank_value IN ('1','2','3','4')) OR (scheme='CCF' AND rank_value IS NOT NULL AND rank_value IN ('A','B','C')) OR (scheme='INDEX' AND rank_value IS NOT NULL AND rank_value IN ('SCIE','SSCI','ESCI','AHCI')) OR (scheme='TOP_CONFERENCE' AND rank_value IS NULL)",
            name="ck_venue_assessment_rank",
        ),
        CheckConstraint(
            "scheme != 'JCR' OR rank_value IS NOT NULL OR impact_factor IS NOT NULL",
            name="ck_venue_assessment_jcr_value",
        ),
        CheckConstraint(
            "(scheme IN ('CAS','TOP_CONFERENCE') OR is_top IS NULL) AND (scheme != 'TOP_CONFERENCE' OR is_top IS NOT NULL)",
            name="ck_venue_assessment_top",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    venue_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("venues.id"), index=True)
    request_key: Mapped[str] = mapped_column(String(64))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    scheme: Mapped[str] = mapped_column(String(24))
    metric_year: Mapped[int] = mapped_column(Integer)
    edition_year: Mapped[int | None] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(240))
    rank_value: Mapped[str | None] = mapped_column(String(24))
    impact_factor: Mapped[Decimal | None] = mapped_column(Numeric(9, 3))
    is_top: Mapped[bool | None] = mapped_column(Boolean)
    source_url: Mapped[str] = mapped_column(String(2000))
    source_label: Mapped[str] = mapped_column(String(240))
    source_kind: Mapped[str] = mapped_column(String(24), default="OWNER_REPORTED")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
