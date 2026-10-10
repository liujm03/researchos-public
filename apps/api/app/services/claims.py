"""Claim evidence assembly is data-only; acceptance is an explicit owner judgment."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import ResearchQuestion
from app.models_analytical import CanonicalAnalyticalNote
from app.models_claims import ClaimEvidence, ClaimReview, ClaimRevision, ResearchClaim
from app.models_server_results import ServerResultArtifact, ServerResultMetric
from app.schemas_claims import (
    ClaimCreate,
    ClaimEvidenceOut,
    ClaimEvidenceSelection,
    ClaimFields,
    ClaimOut,
    ClaimReviewOut,
    ClaimReviewRequest,
    ClaimRevise,
    ClaimRevisionOut,
)
from app.services import canonical_reproduction as canonical
from app.services import research_briefs as briefs
from app.services import server_results as results
from app.services.common import cursor_filter, encode_cursor, register_entity
from app.services.note_trash import require_selectable_job
from app.services.project_note_scope import canonical_in_project
from app.services.projects import get_project

FIELDS = tuple(ClaimFields.model_fields)
EVIDENCE_FIELDS = tuple(
    k
    for k in ClaimEvidence.__table__.columns.keys()
    if k not in {"id", "revision_id", "claim_id", "project_id", "user_id"}
)


def fail(code: str, message: str, status: int = 409) -> DomainError:
    return DomainError(code, message, status, details={"committed": False})


def get(db: Session, owner: uuid.UUID, identity: uuid.UUID, *, lock: bool = False) -> ResearchClaim:
    q = (
        select(ResearchClaim)
        .where(ResearchClaim.id == identity, ResearchClaim.user_id == owner)
        .execution_options(populate_existing=True)
    )
    row = db.scalar(q.with_for_update() if lock else q)
    if row is None:
        raise fail("NOT_FOUND", "Owned claim not found", 404)
    get_project(db, owner, row.project_id)
    return row


def latest(db: Session, row: ResearchClaim) -> ClaimRevision:
    rev = db.scalar(
        select(ClaimRevision)
        .where(
            ClaimRevision.claim_id == row.id,
            ClaimRevision.user_id == row.user_id,
            ClaimRevision.project_id == row.project_id,
            ClaimRevision.revision == row.revision,
        )
        .execution_options(populate_existing=True)
    )
    if rev is None:
        raise fail("CLAIM_REVISION_INVALID", "Current revision missing")
    return rev


def revision(db: Session, row: ResearchClaim, identity: uuid.UUID) -> ClaimRevision:
    rev = db.scalar(
        select(ClaimRevision)
        .where(
            ClaimRevision.id == identity,
            ClaimRevision.claim_id == row.id,
            ClaimRevision.user_id == row.user_id,
            ClaimRevision.project_id == row.project_id,
        )
        .execution_options(populate_existing=True)
    )
    if rev is None:
        raise fail("NOT_FOUND", "Owned claim revision not found", 404)
    return rev


def evidence(db: Session, rev: ClaimRevision) -> list[ClaimEvidence]:
    return list(
        db.scalars(
            select(ClaimEvidence)
            .where(
                ClaimEvidence.revision_id == rev.id,
                ClaimEvidence.user_id == rev.user_id,
                ClaimEvidence.project_id == rev.project_id,
            )
            .order_by(ClaimEvidence.position)
            .execution_options(populate_existing=True)
        )
    )


def evidence_values(source: ClaimEvidence) -> dict[str, Any]:
    return {k: getattr(source, k) for k in EVIDENCE_FIELDS}


def evidence_hash(db: Session, rev: ClaimRevision) -> str:
    return briefs.digest([evidence_values(x) for x in evidence(db, rev)])


def snapshot(db: Session, rev: ClaimRevision) -> dict[str, Any]:
    return {
        "claim_id": str(rev.claim_id),
        "revision_id": str(rev.id),
        "project_id": str(rev.project_id),
        "owner_id": str(rev.user_id),
        "revision": rev.revision,
        "fields": {k: getattr(rev, k) for k in FIELDS},
        "evidence_sha256": evidence_hash(db, rev),
    }


def intact(db: Session, rev: ClaimRevision) -> bool:
    return (
        evidence_hash(db, rev) == rev.evidence_sha256
        and briefs.digest(snapshot(db, rev)) == rev.sha256
        and all(briefs.digest(s.source_facts) == s.source_sha256 for s in evidence(db, rev))
    )


def freeze_source(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    choice: ClaimEvidenceSelection,
    *,
    existing_reference: bool = False,
) -> dict[str, Any]:
    data: dict[str, Any] = {k: None for k in EVIDENCE_FIELDS}
    data.update(
        source_kind=choice.source_kind, relation=choice.relation, rationale=choice.rationale
    )
    if choice.source_kind == "OWNER_OBSERVATION":
        data["observation"] = choice.observation
        facts: dict[str, Any] = {
            "owner_id": str(owner),
            "project_id": str(project),
            "origin": "OWNER_OBSERVATION_UNVERIFIED",
            "observation": choice.observation,
        }
    elif choice.source_kind == "CANONICAL_QUOTE":
        note = db.scalar(
            select(CanonicalAnalyticalNote).where(
                CanonicalAnalyticalNote.id == choice.canonical_note_id,
                CanonicalAnalyticalNote.user_id == owner,
            )
        )
        if note is None:
            raise fail("NOT_FOUND", "Owned canonical note not found", 404)
        if not existing_reference:
            require_selectable_job(db, owner, note.job_id)
        from app.models import PaperAnalysisJob

        job = db.scalar(
            select(PaperAnalysisJob).where(
                PaperAnalysisJob.id == note.job_id, PaperAnalysisJob.user_id == owner
            )
        )
        if job is None:
            raise fail("CLAIM_SOURCE_INVALID", "Reading job unavailable")
        m = canonical.material(db, owner, job.paper_id, note.id)
        if not canonical_in_project(db, owner, note.id, project, m.paper.id):
            raise fail(
                "CLAIM_PAPER_NOT_LINKED",
                "Classify the reading note under this project before selecting its canonical quote",
            )
        if (
            m.note.sha256 != choice.expected_note_sha256
            or m.note.markdown[choice.start_offset : choice.end_offset] != choice.exact_quote
        ):
            raise fail("CLAIM_SOURCE_CHANGED", "Canonical quote or hash changed")
        facts = m.identity()
        data.update(
            canonical_note_id=m.note.id,
            paper_id=m.paper.id,
            paper_title=m.paper.title,
            note_sha256=m.note.sha256,
            reading_job_id=m.job.id,
            reading_plan_id=m.plan.id,
            start_offset=choice.start_offset,
            end_offset=choice.end_offset,
            exact_quote=choice.exact_quote,
        )
    else:
        assert choice.result_id is not None
        row = results.get_result(db, owner, project, choice.result_id)
        if (
            row.status != "READY"
            or row.result_sha256 != choice.expected_result_sha256
            or not results._intact(db, row)
        ):
            raise fail(
                "CLAIM_SOURCE_CHANGED", "Server result is not the current intact ready source"
            )
        facts = {
            "result_id": str(row.id),
            "result_sha256": row.result_sha256,
            "receipt_sha256": row.receipt_sha256,
            "receipt_id": row.receipt_id,
            "server_identity": row.server_identity,
            "claimed_run_status": row.claimed_run_status,
            "origin_verification": row.origin_verification,
            "validation_status": row.validation_status,
            "gaps": row.gaps,
            "git_commit": row.git_commit,
            "protocol_sha256": row.protocol_sha256,
            "dataset_sha256": row.dataset_sha256,
            "config_sha256": row.config_sha256,
            "execution_authorized": False,
        }
        data.update(
            result_id=row.id,
            result_sha256=row.result_sha256,
            protocol_sha256=row.protocol_sha256,
            dataset_sha256=row.dataset_sha256,
        )
        model = (
            ServerResultMetric if choice.source_kind == "RESULT_METRIC" else ServerResultArtifact
        )
        child_id = choice.metric_id if choice.source_kind == "RESULT_METRIC" else choice.artifact_id
        child: Any = db.scalar(
            select(model)
            .where(
                model.id == child_id,
                model.result_id == row.id,
                model.project_id == project,
                model.user_id == owner,
            )
            .execution_options(populate_existing=True)
        )
        if child is None:
            raise fail(
                "NOT_FOUND", "Selected result child not found in this owner/project/result", 404
            )
        if choice.source_kind == "RESULT_METRIC":
            data.update(
                metric_id=child.id,
                metric_name=child.name,
                metric_value=child.value,
                metric_unit=child.unit,
                metric_split=child.split,
                evaluation_protocol=child.evaluation_protocol,
            )
            facts["metric"] = {
                k: getattr(child, k)
                for k in ("name", "value", "unit", "split", "evaluation_protocol")
            }
        else:
            data.update(
                artifact_id=child.id,
                artifact_path=child.path,
                artifact_sha256=child.sha256,
                artifact_verification=child.verification,
            )
            facts["artifact"] = {
                k: (
                    str(getattr(child, k))
                    if isinstance(getattr(child, k), uuid.UUID)
                    else getattr(child, k)
                )
                for k in (
                    "path",
                    "sha256",
                    "size_bytes",
                    "mime_type",
                    "included",
                    "verification",
                    "attachment_id",
                    "actual_sha256",
                    "actual_size_bytes",
                )
            }
    data["source_facts"] = facts
    data["source_sha256"] = briefs.digest(facts)
    return data


def source_current(db: Session, source: ClaimEvidence) -> bool:
    try:
        values: dict[str, Any] = {
            "source_kind": source.source_kind,
            "relation": source.relation,
            "rationale": source.rationale,
        }
        if source.source_kind.startswith("RESULT_"):
            values.update(result_id=source.result_id, expected_result_sha256=source.result_sha256)
            values["metric_id" if source.source_kind == "RESULT_METRIC" else "artifact_id"] = (
                source.metric_id if source.source_kind == "RESULT_METRIC" else source.artifact_id
            )
        elif source.source_kind == "CANONICAL_QUOTE":
            values.update(
                canonical_note_id=source.canonical_note_id,
                expected_note_sha256=source.note_sha256,
                start_offset=source.start_offset,
                end_offset=source.end_offset,
                exact_quote=source.exact_quote,
            )
        else:
            values["observation"] = source.observation
        fresh = freeze_source(
            db,
            source.user_id,
            source.project_id,
            ClaimEvidenceSelection(**values),
            existing_reference=True,
        )
        old = evidence_values(source)
        old.pop("position")
        fresh.pop("position")
        return fresh == old
    except (DomainError, ValueError, TypeError, KeyError):
        return False


def current(db: Session, rev: ClaimRevision) -> bool:
    return intact(db, rev) and all(source_current(db, x) for x in evidence(db, rev))


def gaps(db: Session, rev: ClaimRevision) -> list[str]:
    found: set[str] = set()
    sources = evidence(db, rev)
    if not any(x.relation == "SUPPORTS" and x.source_kind != "OWNER_OBSERVATION" for x in sources):
        found.add("NO_INDEPENDENT_SUPPORT_SOURCE")
    if any(x.relation == "REFUTES" for x in sources):
        found.add("COUNTEREVIDENCE_PRESENT")
    if not rev.conditions.strip():
        found.add("CONDITIONS_UNSPECIFIED")
    if not rev.evaluation_criteria.strip():
        found.add("EVALUATION_CRITERIA_UNSPECIFIED")
    protocols = {
        (s.protocol_sha256, s.dataset_sha256, s.metric_split, s.evaluation_protocol, s.metric_unit)
        for s in sources
        if s.source_kind == "RESULT_METRIC"
    }
    if len(protocols) > 1:
        found.add("INCOMPATIBLE_EVALUATION_CONTEXTS")
    if (
        len({(s.metric_name, s.metric_unit) for s in sources if s.source_kind == "RESULT_METRIC"})
        > 1
    ):
        found.add("MIXED_METRIC_DEFINITIONS")
    for s in sources:
        if not source_current(db, s):
            found.add("SOURCE_CHANGED_OR_UNAVAILABLE")
        if s.source_kind == "OWNER_OBSERVATION":
            found.add("OWNER_OBSERVATION_UNVERIFIED")
        elif s.source_kind == "CANONICAL_QUOTE":
            found.add("AI_DERIVED_NOTE_NOT_AUTHOR_FACT")
        else:
            if s.source_facts.get("origin_verification") != "CONFIGURED_KEY_SIGNATURE":
                found.add("SERVER_ORIGIN_UNVERIFIED")
            if s.source_facts.get("claimed_run_status") != "COMPLETED":
                found.add("SERVER_RUN_NOT_COMPLETED")
            if s.source_facts.get("gaps"):
                found.add("SERVER_RECEIPT_GAPS")
            if s.source_kind == "RESULT_METRIC" and (
                not s.protocol_sha256
                or not s.dataset_sha256
                or not s.evaluation_protocol
                or not s.metric_split
            ):
                found.add("EVALUATION_PROTOCOL_INCOMPLETE")
            if s.source_kind == "RESULT_ARTIFACT" and s.artifact_verification != "BYTES_VERIFIED":
                found.add("ARTIFACT_BYTES_UNVERIFIED")
    if not intact(db, rev):
        found.add("CLAIM_INTEGRITY_INVALID")
    if any(not review_intact(r) for r in review_rows(db, rev)):
        found.add("CLAIM_REVIEW_INTEGRITY_INVALID")
    return sorted(found)


def review_intact(row: ClaimReview) -> bool:
    try:
        request = ClaimReviewRequest(
            revision_id=row.revision_id,
            expected_revision_sha256=row.revision_sha256,
            expected_evidence_sha256=row.evidence_sha256,
            decision=row.decision,
            conclusion=row.conclusion,
            acknowledge_gaps=row.acknowledge_gaps,
            idempotency_key=row.idempotency_key,
        )
        return briefs.digest(request.model_dump(mode="json")) == row.request_sha256
    except (ValueError, TypeError):
        return False


def review_rows(db: Session, rev: ClaimRevision) -> list[ClaimReview]:
    return list(
        db.scalars(
            select(ClaimReview)
            .where(ClaimReview.revision_id == rev.id, ClaimReview.user_id == rev.user_id)
            .order_by(ClaimReview.reviewed_at, ClaimReview.id)
        )
    )


def revision_out(db: Session, rev: ClaimRevision) -> ClaimRevisionOut:
    reviews = review_rows(db, rev)
    decisions = [
        r
        for r in reviews
        if r.decision != "COMMENT"
        and r.revision_sha256 == rev.sha256
        and r.evidence_sha256 == rev.evidence_sha256
        and review_intact(r)
    ]
    state = "CANDIDATE"
    if decisions and current(db, rev) and all(review_intact(r) for r in reviews):
        state = "OWNER_ACCEPTED" if decisions[-1].decision == "ACCEPT" else "OWNER_REJECTED"
    sources = []
    for s in evidence(db, rev):
        values = {
            k: getattr(s, k)
            for k in ClaimEvidenceOut.model_fields
            if k not in {"context_current", "origin"}
        }
        sources.append(
            ClaimEvidenceOut(
                **values,
                context_current=source_current(db, s),
                origin="AI_DERIVED"
                if s.source_kind == "CANONICAL_QUOTE"
                else "OWNER_OBSERVATION_UNVERIFIED"
                if s.source_kind == "OWNER_OBSERVATION"
                else s.source_facts.get("origin_verification", "UNKNOWN"),
            )
        )
    return ClaimRevisionOut(
        **{k: getattr(rev, k) for k in FIELDS},
        id=rev.id,
        claim_id=rev.claim_id,
        project_id=rev.project_id,
        revision=rev.revision,
        sha256=rev.sha256,
        evidence_sha256=rev.evidence_sha256,
        created_at=rev.created_at,
        evidence=sources,
        reviews=[ClaimReviewOut.model_validate(r) for r in reviews],
        integrity_valid=intact(db, rev),
        context_current=current(db, rev),
        gaps=gaps(db, rev),
        scientific_state=state,
    )


def out(db: Session, row: ResearchClaim) -> ClaimOut:
    return ClaimOut(
        id=row.id,
        project_id=row.project_id,
        title=row.title,
        revision=row.revision,
        created_at=row.created_at,
        current=revision_out(db, latest(db, row)),
    )


def lookup(db: Session, owner: uuid.UUID, key: str) -> ResearchClaim:
    row = db.scalar(
        select(ResearchClaim).where(ResearchClaim.user_id == owner, ResearchClaim.create_key == key)
    )
    if row is None:
        raise fail("NOT_FOUND", "Owned claim capture not found", 404)
    return row


def write_revision(
    db: Session, row: ResearchClaim, body: ClaimCreate | ClaimRevise
) -> ClaimRevision:
    if (
        body.research_question_id is not None
        and db.scalar(
            select(ResearchQuestion).where(
                ResearchQuestion.id == body.research_question_id,
                ResearchQuestion.project_id == row.project_id,
            )
        )
        is None
    ):
        raise fail("NOT_FOUND", "Research question is not in the owned project", 404)
    rev = ClaimRevision(
        id=uuid.uuid4(),
        claim_id=row.id,
        project_id=row.project_id,
        user_id=row.user_id,
        revision=row.revision,
        **{k: getattr(body, k) for k in FIELDS},
        sha256="0" * 64,
        evidence_sha256="0" * 64,
        idempotency_key=body.idempotency_key,
        request_sha256=briefs.digest(body.model_dump(mode="json")),
    )
    frozen = [freeze_source(db, row.user_id, row.project_id, x) for x in body.evidence]
    hashes = [briefs.digest({k: v for k, v in x.items() if k != "position"}) for x in frozen]
    if len(set(hashes)) != len(hashes):
        raise fail("CLAIM_DUPLICATE_EVIDENCE", "Same evidence selection repeated", 422)
    db.add(rev)
    db.flush()
    for pos, values in enumerate(frozen):
        values["position"] = pos
        db.add(
            ClaimEvidence(
                revision_id=rev.id,
                claim_id=row.id,
                project_id=row.project_id,
                user_id=row.user_id,
                **values,
            )
        )
    db.flush()
    rev.evidence_sha256 = evidence_hash(db, rev)
    rev.sha256 = briefs.digest(snapshot(db, rev))
    row.title = rev.title
    row.text = rev.text
    return rev


def create(db: Session, owner: uuid.UUID, body: ClaimCreate) -> ResearchClaim:
    sha = briefs.digest(body.model_dump(mode="json"))
    existing = db.scalar(
        select(ResearchClaim).where(
            ResearchClaim.user_id == owner, ResearchClaim.create_key == body.idempotency_key
        )
    )
    if existing:
        if existing.create_sha256 != sha:
            raise fail("IDEMPOTENCY_CONFLICT", "Claim key used with different input")
        return existing
    get_project(db, owner, body.project_id)
    try:
        row = ResearchClaim(
            id=register_entity(db, owner, "claim"),
            user_id=owner,
            project_id=body.project_id,
            revision=1,
            title=body.title,
            text=body.text,
            create_key=body.idempotency_key,
            create_sha256=sha,
        )
        db.add(row)
        db.flush()
        write_revision(db, row, body)
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(ResearchClaim).where(
                ResearchClaim.user_id == owner, ResearchClaim.create_key == body.idempotency_key
            )
        )
        if existing and existing.create_sha256 == sha:
            return existing
        raise fail("IDEMPOTENCY_CONFLICT", "Another capture won; inspect before retry") from None
    except Exception:
        db.rollback()
        raise


def revise(db: Session, owner: uuid.UUID, identity: uuid.UUID, body: ClaimRevise) -> ResearchClaim:
    row = get(db, owner, identity, lock=True)
    sha = briefs.digest(body.model_dump(mode="json"))
    existing = db.scalar(
        select(ClaimRevision).where(
            ClaimRevision.claim_id == row.id, ClaimRevision.idempotency_key == body.idempotency_key
        )
    )
    if existing:
        if existing.request_sha256 != sha:
            raise fail("IDEMPOTENCY_CONFLICT", "Revision key used with different input")
        return row
    if db.scalar(
        select(ClaimReview).where(
            ClaimReview.claim_id == row.id, ClaimReview.idempotency_key == body.idempotency_key
        )
    ):
        raise fail("IDEMPOTENCY_CONFLICT", "Key belongs to a review")
    prior = latest(db, row)
    if prior.sha256 != body.expected_revision_sha256 or not intact(db, prior):
        raise fail("CLAIM_REVISION_CHANGED", "Reload intact current claim revision")
    try:
        row.revision += 1
        write_revision(db, row, body)
        db.commit()
        db.refresh(row)
    except IntegrityError:
        db.rollback()
        raise fail("CLAIM_REVISION_CHANGED", "Another revision won; inspect receipt") from None
    except Exception:
        db.rollback()
        raise
    return row


def review(
    db: Session, owner: uuid.UUID, identity: uuid.UUID, body: ClaimReviewRequest
) -> ClaimReview:
    row = get(db, owner, identity, lock=True)
    sha = briefs.digest(body.model_dump(mode="json"))
    existing = db.scalar(
        select(ClaimReview).where(
            ClaimReview.claim_id == row.id,
            ClaimReview.user_id == owner,
            ClaimReview.idempotency_key == body.idempotency_key,
        )
    )
    if existing:
        if existing.request_sha256 != sha:
            raise fail("IDEMPOTENCY_CONFLICT", "Review key used with different input")
        return existing
    if db.scalar(
        select(ClaimRevision).where(
            ClaimRevision.claim_id == row.id, ClaimRevision.idempotency_key == body.idempotency_key
        )
    ):
        raise fail("IDEMPOTENCY_CONFLICT", "Key belongs to revision")
    rev = revision(db, row, body.revision_id)
    if not body.conclusion.strip():
        raise fail("VALIDATION_ERROR", "Owner conclusion required", 422)
    if (
        body.expected_revision_sha256 != rev.sha256
        or body.expected_evidence_sha256 != rev.evidence_sha256
        or not current(db, rev)
    ):
        raise fail(
            "CLAIM_SOURCE_CHANGED", "Claim/evidence/source changed; refresh or create revision"
        )
    if gaps(db, rev) and not body.acknowledge_gaps:
        raise fail("CLAIM_GAPS_ACK_REQUIRED", "Acknowledge displayed scientific evidence gaps")
    previous = db.scalar(
        select(ClaimReview)
        .where(ClaimReview.claim_id == row.id, ClaimReview.user_id == owner)
        .order_by(ClaimReview.reviewed_at.desc(), ClaimReview.id.desc())
        .limit(1)
    )
    review_time = datetime.now(UTC)
    if previous:
        last_time = (
            previous.reviewed_at.replace(tzinfo=UTC)
            if previous.reviewed_at.tzinfo is None
            else previous.reviewed_at
        )
        if review_time <= last_time:
            review_time = last_time + timedelta(microseconds=1)
    found = ClaimReview(
        id=uuid.uuid4(),
        claim_id=row.id,
        project_id=row.project_id,
        user_id=owner,
        revision_id=rev.id,
        revision_sha256=rev.sha256,
        evidence_sha256=rev.evidence_sha256,
        decision=body.decision,
        conclusion=body.conclusion,
        acknowledge_gaps=body.acknowledge_gaps,
        idempotency_key=body.idempotency_key,
        request_sha256=sha,
        reviewed_at=review_time,
    )
    try:
        db.add(found)
        db.commit()
        db.refresh(found)
        return found
    except IntegrityError:
        db.rollback()
        raise fail("CLAIM_REVIEW_CHANGED", "Another review won; inspect receipt") from None


def list_claims(
    db: Session, owner: uuid.UUID, project: uuid.UUID | None, limit: int, cursor: str | None
) -> tuple[list[ResearchClaim], str | None]:
    if project:
        get_project(db, owner, project)
    q = select(ResearchClaim).where(
        ResearchClaim.user_id == owner, cursor_filter(ResearchClaim, cursor)
    )
    if project:
        q = q.where(ResearchClaim.project_id == project)
    rows = list(
        db.scalars(
            q.order_by(ResearchClaim.created_at.desc(), ResearchClaim.id.desc()).limit(limit + 1)
        )
    )
    return rows[:limit], encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(
        rows
    ) > limit else None
