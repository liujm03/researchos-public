import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.venue_ratings import VenueRatingProvider
from app.errors import DomainError
from app.models import Paper, Venue
from app.models_venue_ratings import VenueAssessment
from app.providers.venue_ratings.registry import get_venue_rating_provider
from app.schemas_venue_ratings import VenueAssessmentCreate, VenueAssessmentOut
from app.services.papers import get_paper
from app.services.zotero_venue_fields import fields_for_paper


def assessments_for_paper(
    db: Session,
    user_id: uuid.UUID,
    paper: Paper,
    *,
    request_key: str | None = None,
    provider: VenueRatingProvider | None = None,
) -> list[VenueAssessmentOut]:
    if paper.user_id != user_id:
        raise DomainError("NOT_FOUND", "Paper not found", 404)
    if paper.venue_id is None:
        return [] if request_key is not None else fields_for_paper(db, user_id, paper)
    query = select(VenueAssessment).where(
        VenueAssessment.user_id == user_id, VenueAssessment.venue_id == paper.venue_id
    )
    if request_key is not None:
        query = query.where(VenueAssessment.request_key == request_key)
    records = [
        VenueAssessmentOut.model_validate(row)
        for row in db.scalars(
            query.order_by(
                VenueAssessment.metric_year.desc(),
                VenueAssessment.checked_at.desc(),
                VenueAssessment.id.desc(),
            )
        )
    ]
    if request_key is not None:
        return records
    records += fields_for_paper(db, user_id, paper)
    venue = db.get(Venue, paper.venue_id)
    if venue is not None:
        records += [
            VenueAssessmentOut.model_validate(row)
            for row in (provider or get_venue_rating_provider()).lookup(venue.name, venue.type)
        ]
    return records


def append_assessment(
    db: Session, user_id: uuid.UUID, paper_id: uuid.UUID, data: VenueAssessmentCreate
) -> VenueAssessment:
    paper = get_paper(db, user_id, paper_id)
    if paper.venue_id is None:
        raise DomainError("VENUE_REQUIRED", "请先补充论文的期刊或会议名称", 422)
    venue = db.get(Venue, paper.venue_id)
    if venue is None:
        raise DomainError("VENUE_REQUIRED", "论文的期刊或会议资料缺失", 422)
    if (
        venue.type == "preprint"
        or (venue.type == "conference" and data.scheme in {"JCR", "CAS", "INDEX"})
        or (venue.type == "journal" and data.scheme == "TOP_CONFERENCE")
    ):
        raise DomainError("VENUE_RATING_MISMATCH", "评价标准与期刊/会议类型不一致", 422)
    payload = data.model_dump(exclude={"request_key"}) | {"venue_id": str(paper.venue_id)}
    digest = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()

    def existing() -> VenueAssessment | None:
        prior = db.scalar(
            select(VenueAssessment).where(
                VenueAssessment.user_id == user_id, VenueAssessment.request_key == data.request_key
            )
        )
        if prior is not None and prior.payload_sha256 != digest:
            raise DomainError(
                "ASSESSMENT_REQUEST_CONFLICT", "相同请求标识已有不同记录，请先核查原回执", 409
            )
        return prior

    prior = existing()
    if prior is not None:
        return prior
    record = VenueAssessment(
        id=uuid.uuid4(),
        user_id=user_id,
        venue_id=paper.venue_id,
        payload_sha256=digest,
        source_kind="OWNER_REPORTED",
        **data.model_dump(),
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = existing()
        if prior is not None:
            return prior
        raise DomainError(
            "ASSESSMENT_CONFLICT", "评级记录保存发生冲突，请先核查回执", 409
        ) from None
    db.refresh(record)
    return record
