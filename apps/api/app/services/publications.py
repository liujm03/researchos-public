"""Local manuscript planning; no model calls, research execution or publication."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import Attachment
from app.models_evidence_bundles import EvidenceBundle
from app.models_publications import (
    Publication,
    PublicationBinding,
    PublicationReview,
    PublicationRevision,
    PublicationSection,
    PublicationSource,
)
from app.schemas_publications import (
    PublicationBindingInput,
    PublicationCreate,
    PublicationFields,
    PublicationOut,
    PublicationPreview,
    PublicationReviewOut,
    PublicationReviewRequest,
    PublicationRevise,
    PublicationRevisionOut,
    PublicationSectionInput,
    PublicationSourceInput,
)
from app.services import claims, evidence_bundles
from app.services.claims import fail as fail
from app.services.common import register_entity
from app.services.projects import get_project
from app.services.research_briefs import digest


def get(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID, *, lock: bool = False
) -> Publication:
    get_project(db, owner, project)
    q = (
        select(Publication)
        .where(
            Publication.id == identity,
            Publication.project_id == project,
            Publication.user_id == owner,
        )
        .execution_options(populate_existing=True)
    )
    row = db.scalar(q.with_for_update() if lock else q)
    if row is None:
        raise fail("NOT_FOUND", "Owned publication not found", 404)
    return row


def latest(db: Session, row: Publication) -> PublicationRevision:
    rev = db.scalar(
        select(PublicationRevision)
        .where(
            PublicationRevision.publication_id == row.id,
            PublicationRevision.user_id == row.user_id,
            PublicationRevision.revision == row.revision,
        )
        .execution_options(populate_existing=True)
    )
    if rev is None:
        raise fail("PUBLICATION_REVISION_INVALID", "Current revision missing")
    return rev


def revision(db: Session, row: Publication, identity: uuid.UUID) -> PublicationRevision:
    rev = db.scalar(
        select(PublicationRevision)
        .where(
            PublicationRevision.id == identity,
            PublicationRevision.publication_id == row.id,
            PublicationRevision.user_id == row.user_id,
        )
        .execution_options(populate_existing=True)
    )
    if rev is None:
        raise fail("NOT_FOUND", "Owned publication revision not found", 404)
    return rev


def children(db: Session, model: Any, rev: PublicationRevision) -> list[Any]:
    return list(
        db.scalars(
            select(model)
            .where(
                model.revision_id == rev.id,
                model.publication_id == rev.publication_id,
                model.project_id == rev.project_id,
                model.user_id == rev.user_id,
            )
            .order_by(model.position)
            .execution_options(populate_existing=True)
        )
    )


def fields(db: Session, rev: PublicationRevision) -> PublicationFields:
    return PublicationFields(
        title=rev.title,
        target_venue=rev.target_venue,
        stage=rev.stage,
        sections=[
            PublicationSectionInput(
                **{k: getattr(s, k) for k in PublicationSectionInput.model_fields}
            )
            for s in children(db, PublicationSection, rev)
        ],
        sources=[
            PublicationSourceInput(
                **{k: getattr(s, k) for k in PublicationSourceInput.model_fields}
            )
            for s in children(db, PublicationSource, rev)
        ],
        bindings=[
            PublicationBindingInput(
                **{k: getattr(s, k) for k in PublicationBindingInput.model_fields}
            )
            for s in children(db, PublicationBinding, rev)
        ],
    )


def source_values(row: PublicationSource) -> dict[str, Any]:
    return {
        k: str(getattr(row, k))
        for k in (
            "bundle_id",
            "expected_bundle_sha256",
            "snapshot_sha256",
            "preview_sha256",
            "attachment_id",
        )
    }


def snapshot(db: Session, rev: PublicationRevision) -> dict[str, Any]:
    return {
        "owner_id": str(rev.user_id),
        "project_id": str(rev.project_id),
        "publication_id": str(rev.publication_id),
        "revision_id": str(rev.id),
        "revision": rev.revision,
        "fields": fields(db, rev).model_dump(mode="json"),
        "source_sha256": rev.source_sha256,
    }


def source_available(db: Session, owner: uuid.UUID, bundle: EvidenceBundle) -> bool:
    attachment = db.scalar(
        select(Attachment)
        .where(Attachment.id == bundle.attachment_id, Attachment.user_id == owner)
        .execution_options(populate_existing=True)
    )
    return bool(
        attachment is not None
        and attachment.deleted_at is None
        and attachment.sha256 == bundle.bundle_sha256
        and attachment.size_bytes == bundle.bundle_size_bytes
        and attachment.object_key
        and attachment.storage_provider
        and evidence_bundles.intact(db, bundle)
    )


def freeze(
    db: Session, owner: uuid.UUID, project: uuid.UUID, body: PublicationFields
) -> tuple[list[dict[str, Any]], list[Any], list[str]]:
    get_project(db, owner, project)
    frozen, details = [], []
    gaps: set[str] = set()
    bundle_rows = {}
    for choice in body.sources:
        bundle = evidence_bundles.get(db, owner, project, choice.bundle_id)
        if (
            bundle.status != "READY"
            or bundle.bundle_sha256 != choice.expected_bundle_sha256
            or not source_available(db, owner, bundle)
            or bundle.attachment_id is None
        ):
            raise fail(
                "PUBLICATION_SOURCE_INVALID",
                "Select an intact READY evidence bundle with its exact SHA",
            )
        detail = evidence_bundles.out(db, bundle)
        details.append(detail)
        bundle_rows[bundle.id] = bundle
        frozen.append(
            {
                "bundle_id": bundle.id,
                "expected_bundle_sha256": bundle.bundle_sha256,
                "snapshot_sha256": bundle.snapshot_sha256,
                "preview_sha256": bundle.preview_sha256,
                "attachment_id": bundle.attachment_id,
            }
        )
        gaps.update("BUNDLE: " + x for x in detail.current_gaps)
        if not detail.context_current:
            gaps.add("BUNDLE_CONTEXT_CHANGED")
        gaps.add("SOURCE_ARTIFACT_BYTES_NOT_INCLUDED")
    section_map = {s.key: s for s in body.sections}
    for binding in body.bindings:
        section = section_map.get(binding.section_key)
        if (
            section is None
            or section.markdown[binding.start_offset : binding.end_offset] != binding.exact_quote
            or binding.end_offset - binding.start_offset != len(binding.exact_quote)
        ):
            raise fail(
                "PUBLICATION_QUOTE_INVALID", "Binding must match exact original section text", 422
            )
        bound_bundle = bundle_rows.get(binding.bundle_id)
        if bound_bundle is None:
            raise fail(
                "PUBLICATION_BINDING_SOURCE", "Binding must use a selected evidence bundle", 422
            )
        claim_data = next(
            (
                c
                for c in bound_bundle.snapshot["claims"]
                if c["id"] == str(binding.claim_revision_id)
                and c["claim_id"] == str(binding.claim_id)
                and c["sha256"] == binding.expected_claim_sha256
            ),
            None,
        )
        if claim_data is None:
            raise fail(
                "PUBLICATION_BINDING_CLAIM",
                "Claim revision is not in the selected frozen bundle",
                422,
            )
        if claim_data["scientific_state"] != "OWNER_ACCEPTED":
            gaps.add("CLAIM_NOT_OWNER_ACCEPTED")
        checks = (binding.format_check, binding.metadata_check, binding.support_check)
        if binding.paper_id is None:
            if any(c != "UNCHECKED" for c in checks):
                raise fail(
                    "PUBLICATION_CITATION_IDENTITY",
                    "Citation checks require an exact paper source",
                    422,
                )
        else:
            if not any(e.get("paper_id") == str(binding.paper_id) for e in claim_data["evidence"]):
                raise fail(
                    "PUBLICATION_CITATION_IDENTITY",
                    "Paper must belong to the selected claim evidence",
                    422,
                )
            if any(c == "UNCHECKED" for c in checks):
                gaps.add("CITATION_CHECKS_INCOMPLETE")
            if any(c == "ISSUE" for c in checks):
                gaps.add("CITATION_ISSUES_PRESENT")
        if binding.relation == "REFUTES":
            gaps.add("COUNTEREVIDENCE_PRESENT")
    required = {"background", "limitations", "key_idea", "challenges", "method", "contributions"}
    complete = {s.key for s in body.sections if s.kind == "SKELETON" and s.markdown.strip()}
    if not required.issubset(complete):
        gaps.add("PAPER_SKELETON_INCOMPLETE")
    if not any(s.kind == "MANUSCRIPT" and s.markdown.strip() for s in body.sections):
        gaps.add("MANUSCRIPT_SECTIONS_MISSING")
    if not body.sources:
        gaps.add("NO_EVIDENCE_BUNDLE_SELECTED")
    if not body.bindings:
        gaps.add("NO_CLAIM_TEXT_BINDINGS")
    return frozen, details, sorted(gaps)


def prepare(
    db: Session, owner: uuid.UUID, project: uuid.UUID, body: PublicationFields
) -> tuple[PublicationPreview, list[dict[str, Any]]]:
    frozen, details, gaps = freeze(db, owner, project, body)
    result = PublicationPreview(
        fields=body,
        preview_sha256=digest(
            {
                "owner_id": str(owner),
                "project_id": str(project),
                "fields": body.model_dump(mode="json"),
                "sources": frozen,
                "contexts": [
                    {
                        "id": str(d.id),
                        "context_current": d.context_current,
                        "gaps": d.current_gaps,
                        "live_sha256": live_sources_sha(db, owner, project, d.snapshot),
                    }
                    for d in details
                ],
                "gaps": gaps,
            }
        ),
        gaps=gaps,
        source_details=details,
    )

    return result, frozen


def preview(
    db: Session, owner: uuid.UUID, project: uuid.UUID, body: PublicationFields
) -> PublicationPreview:
    return prepare(db, owner, project, body)[0]


def live_sources_sha(
    db: Session, owner: uuid.UUID, project: uuid.UUID, frozen: dict[str, Any]
) -> str:
    current = []
    for selected in frozen["claims"]:
        try:
            claim = claims.get(db, owner, uuid.UUID(selected["claim_id"]))
            if claim.project_id != project:
                raise fail("PUBLICATION_SOURCE_SCOPE", "Claim belongs to another project")
            rev = claims.revision(db, claim, uuid.UUID(selected["id"]))
            current.append(claims.revision_out(db, rev).model_dump(mode="json"))
        except DomainError as error:
            current.append({"id": selected["id"], "unavailable": error.code})
    return digest(current)


def intact(db: Session, rev: PublicationRevision) -> bool:
    try:
        return (
            digest([source_values(s) for s in children(db, PublicationSource, rev)])
            == rev.source_sha256
            and digest(snapshot(db, rev)) == rev.sha256
        )
    except (ValueError, KeyError, TypeError):
        return False


def review_intact(row: PublicationReview) -> bool:
    try:
        body = PublicationReviewRequest(
            revision_id=row.revision_id,
            expected_revision_sha256=row.revision_sha256,
            decision=row.decision,
            conclusion=row.conclusion,
            acknowledge_gaps=row.acknowledge_gaps,
            idempotency_key=row.idempotency_key,
        )
        return digest(body.model_dump(mode="json")) == row.request_sha256
    except ValueError:
        return False


def revision_out(db: Session, rev: PublicationRevision) -> PublicationRevisionOut:
    value = fields(db, rev)
    integrity = intact(db, rev)
    details: list[Any] = []
    current = integrity
    try:
        fresh, details, gaps = freeze(db, rev.user_id, rev.project_id, value)
        current = (
            current
            and digest(fresh) == rev.source_sha256
            and all(d.context_current for d in details)
        )
    except Exception as exc:
        from app.errors import DomainError

        if not isinstance(exc, (DomainError, ValueError, KeyError)):
            raise
        current = False
        gaps = ["SOURCE_CHANGED_OR_UNAVAILABLE"]
    if not integrity:
        gaps.append("PUBLICATION_INTEGRITY_INVALID")
    reviews = list(
        db.scalars(
            select(PublicationReview)
            .where(
                PublicationReview.revision_id == rev.id, PublicationReview.user_id == rev.user_id
            )
            .order_by(PublicationReview.reviewed_at, PublicationReview.id)
        )
    )
    review_valid = all(review_intact(r) for r in reviews)
    if not review_valid:
        gaps.append("PUBLICATION_REVIEW_INTEGRITY_INVALID")
    decisions = [
        r
        for r in reviews
        if r.decision != "COMMENT" and r.revision_sha256 == rev.sha256 and review_intact(r)
    ]
    state = "CANDIDATE"
    if current and review_valid and decisions:
        state = "OWNER_ACCEPTED" if decisions[-1].decision == "ACCEPT" else "OWNER_REJECTED"
    return PublicationRevisionOut(
        **value.model_dump(),
        id=rev.id,
        publication_id=rev.publication_id,
        project_id=rev.project_id,
        revision=rev.revision,
        sha256=rev.sha256,
        source_sha256=rev.source_sha256,
        created_at=rev.created_at,
        source_details=details,
        integrity_valid=integrity,
        context_current=current,
        gaps=sorted(set(gaps)),
        reviews=[PublicationReviewOut.model_validate(r) for r in reviews],
        owner_review_state=state,
    )


def out(db: Session, row: Publication) -> PublicationOut:
    return PublicationOut(
        id=row.id,
        project_id=row.project_id,
        title=row.title,
        revision=row.revision,
        created_at=row.created_at,
        current=revision_out(db, latest(db, row)),
    )


def lookup(db: Session, owner: uuid.UUID, project: uuid.UUID, key: str) -> Publication:
    get_project(db, owner, project)
    row = db.scalar(
        select(Publication).where(
            Publication.user_id == owner,
            Publication.project_id == project,
            Publication.create_key == key,
        )
    )
    if row is None:
        raise fail("NOT_FOUND", "Owned publication capture not found", 404)
    return row


def write(
    db: Session,
    row: Publication,
    body: PublicationCreate | PublicationRevise,
    frozen: list[dict[str, Any]],
    gaps: list[str],
) -> None:
    value = PublicationFields(**{k: getattr(body, k) for k in PublicationFields.model_fields})
    if gaps and not body.acknowledge_gaps:
        raise fail(
            "PUBLICATION_GAPS_REQUIRE_ACK", "Acknowledge manuscript/source gaps before saving"
        )
    rev = PublicationRevision(
        id=uuid.uuid4(),
        publication_id=row.id,
        user_id=row.user_id,
        project_id=row.project_id,
        revision=row.revision,
        title=value.title,
        target_venue=value.target_venue,
        stage=value.stage,
        sha256="0" * 64,
        source_sha256=digest(frozen),
        idempotency_key=body.idempotency_key,
        request_sha256=digest(body.model_dump(mode="json")),
        created_at=datetime.now(UTC),
    )
    db.add(rev)
    db.flush()
    scope = dict(
        revision_id=rev.id, publication_id=row.id, project_id=row.project_id, user_id=row.user_id
    )
    for pos, s in enumerate(value.sections):
        db.add(PublicationSection(**scope, position=pos, **s.model_dump()))
    for pos, frozen_source in enumerate(frozen):
        db.add(PublicationSource(**scope, position=pos, **frozen_source))
    db.flush()
    for pos, b in enumerate(value.bindings):
        db.add(PublicationBinding(**scope, position=pos, **b.model_dump()))
    db.flush()
    rev.sha256 = digest(snapshot(db, rev))


def create(
    db: Session, owner: uuid.UUID, project: uuid.UUID, body: PublicationCreate
) -> Publication:
    get_project(db, owner, project)
    request_sha = digest(body.model_dump(mode="json"))
    old = db.scalar(
        select(Publication).where(
            Publication.user_id == owner,
            Publication.project_id == project,
            Publication.create_key == body.idempotency_key,
        )
    )
    if old:
        if old.create_sha256 != request_sha:
            raise fail("IDEMPOTENCY_CONFLICT", "Same key has different input")
        return old
    value = PublicationFields(**{k: getattr(body, k) for k in PublicationFields.model_fields})
    prepared, frozen = prepare(db, owner, project, value)
    if prepared.preview_sha256 != body.expected_preview_sha256:
        raise fail("PUBLICATION_PREVIEW_CHANGED", "Publication preview changed; inspect it again")
    try:
        row = Publication(
            id=register_entity(db, owner, "publication"),
            user_id=owner,
            project_id=project,
            revision=1,
            title=body.title,
            create_key=body.idempotency_key,
            create_sha256=request_sha,
        )
        db.add(row)
        db.flush()
        write(db, row, body, frozen, prepared.gaps)
        db.commit()
        return row
    except IntegrityError:
        db.rollback()
        old = lookup(db, owner, project, body.idempotency_key)
        if old.create_sha256 != request_sha:
            raise fail("IDEMPOTENCY_CONFLICT", "Same key has different input") from None
        return old
    except Exception:
        db.rollback()
        raise


def revise(
    db: Session, owner: uuid.UUID, project: uuid.UUID, identity: uuid.UUID, body: PublicationRevise, *, _commit: bool = True
) -> Publication:
    row = get(db, owner, project, identity, lock=True)
    request_sha = digest(body.model_dump(mode="json"))
    previous = db.scalar(
        select(PublicationRevision).where(
            PublicationRevision.publication_id == row.id,
            PublicationRevision.idempotency_key == body.idempotency_key,
        )
    )
    if previous:
        if previous.request_sha256 != request_sha:
            raise fail("IDEMPOTENCY_CONFLICT", "Same key has different input")
        return row
    if latest(db, row).sha256 != body.expected_revision_sha256:
        raise fail("PUBLICATION_REVISION_CHANGED", "Publication changed; reload before saving")
    value = PublicationFields(**{k: getattr(body, k) for k in PublicationFields.model_fields})
    prepared, frozen = prepare(db, owner, project, value)
    if prepared.preview_sha256 != body.expected_preview_sha256:
        raise fail("PUBLICATION_PREVIEW_CHANGED", "Publication preview changed; inspect it again")
    try:
        row.revision += 1
        row.title = body.title
        write(db, row, body, frozen, prepared.gaps)
        if _commit:
            db.commit()
        else:
            db.flush()
        return row
    except Exception:
        db.rollback()
        raise


def review(
    db: Session,
    owner: uuid.UUID,
    project: uuid.UUID,
    identity: uuid.UUID,
    body: PublicationReviewRequest,
) -> PublicationReview:
    row = get(db, owner, project, identity, lock=True)
    request_sha = digest(body.model_dump(mode="json"))
    old = db.scalar(
        select(PublicationReview).where(
            PublicationReview.publication_id == row.id,
            PublicationReview.idempotency_key == body.idempotency_key,
        )
    )
    if old:
        if old.request_sha256 != request_sha:
            raise fail("IDEMPOTENCY_CONFLICT", "Same key has different input")
        return old
    rev = revision(db, row, body.revision_id)
    detail = revision_out(db, rev)
    if (
        rev.sha256 != body.expected_revision_sha256
        or not detail.integrity_valid
        or not detail.context_current
    ):
        raise fail(
            "PUBLICATION_REVIEW_SOURCE_CHANGED", "Exact manuscript or its evidence sources changed"
        )
    if not body.conclusion.strip():
        raise fail("PUBLICATION_REVIEW_EMPTY", "Review conclusion is required", 422)
    if detail.gaps and not body.acknowledge_gaps:
        raise fail(
            "PUBLICATION_GAPS_REQUIRE_ACK", "Acknowledge manuscript/source gaps before review"
        )
    now = datetime.now(UTC)
    if detail.reviews:
        last = detail.reviews[-1].reviewed_at.replace(tzinfo=UTC)
        now = max(now, last + timedelta(microseconds=1))
    record = PublicationReview(
        revision_id=rev.id,
        publication_id=row.id,
        user_id=owner,
        project_id=project,
        revision_sha256=rev.sha256,
        decision=body.decision,
        conclusion=body.conclusion,
        acknowledge_gaps=body.acknowledge_gaps,
        idempotency_key=body.idempotency_key,
        request_sha256=request_sha,
        reviewed_at=now,
    )
    db.add(record)
    db.commit()
    return record
