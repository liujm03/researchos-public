"""Frozen metadata review and atomic, append-only registry source adoption."""

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import cast

from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import experiments as experiment_schema
from app.domain import repository_imports as schema
from app.domain.repositories import OpenSourceRepositoryProvider
from app.errors import DomainError
from app.models import (
    CodeRepository,
    Dataset,
    Model,
    RepositoryBinding,
    RepositoryImportPreview,
    RepositorySourceSnapshot,
    ResearchEntity,
    ResearchEvent,
    User,
)
from app.providers.registry import repository_provider
from app.services import experiment_registries as registry

MAX_CANDIDATE_BYTES = 1_048_576
MAX_RAW_METADATA_BYTES = 262_144
TARGET_KIND: dict[str, str] = {
    "code": "code_repository",
    "space": "code_repository",
    "model": "model",
    "dataset": "dataset",
}


def _hash_payload(payload: dict[str, object]) -> str:
    try:
        content = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as error:
        raise DomainError(
            "SOURCE_METADATA_INVALID", "Repository metadata is not a finite JSON receipt", 422
        ) from error
    if len(content) > MAX_CANDIDATE_BYTES:
        raise DomainError(
            "SOURCE_METADATA_TOO_LARGE", "Repository metadata receipt exceeds its bound", 413
        )
    return hashlib.sha256(content).hexdigest()


def _candidate(
    record: RepositoryImportPreview | RepositorySourceSnapshot,
) -> schema.RepositoryCandidateSnapshot:
    if _hash_payload(record.candidate_payload) != record.snapshot_sha256:
        raise DomainError(
            "INVALID_SOURCE_SNAPSHOT", "Frozen repository source receipt changed", 409
        )
    try:
        candidate = schema.RepositoryCandidateSnapshot.model_validate(record.candidate_payload)
    except ValidationError as error:
        raise DomainError(
            "INVALID_SOURCE_SNAPSHOT", "Frozen repository metadata is invalid", 409
        ) from error
    if (
        candidate.source_hash != record.source_hash
        or candidate.canonical_url != record.canonical_url
    ):
        raise DomainError(
            "INVALID_SOURCE_SNAPSHOT", "Frozen repository source identity differs", 409
        )
    return candidate


def get_preview(
    db: Session, user_id: uuid.UUID, preview_id: uuid.UUID, *, lock: bool = False
) -> RepositoryImportPreview:
    return registry.owned(db, user_id, RepositoryImportPreview, preview_id, lock=lock)


def _binding_match(
    db: Session, user_id: uuid.UUID, candidate: schema.RepositoryCandidateOut
) -> tuple[RepositoryBinding | None, bool]:
    rows = list(
        db.scalars(
            select(RepositoryBinding).where(
                RepositoryBinding.user_id == user_id,
                RepositoryBinding.provider_key == candidate.provider_key,
                RepositoryBinding.repo_kind == candidate.repo_kind,
                or_(
                    RepositoryBinding.repo_id == candidate.repo_id,
                    RepositoryBinding.provider_id == candidate.provider_id,
                ),
            )
        )
    )
    if not rows:
        return None, False
    if len(rows) != 1:
        return None, True
    binding = rows[0]
    return (
        binding,
        binding.repo_id != candidate.repo_id or binding.provider_id != candidate.provider_id,
    )


async def create_preview(
    db: Session,
    user_id: uuid.UUID,
    body: schema.RepositoryPreviewRequest,
    provider: OpenSourceRepositoryProvider | None = None,
) -> RepositoryImportPreview:
    from app.domain.repository_identity import normalize_repository_ref

    reference = normalize_repository_ref(
        body.repository,
        provider_key=body.provider_key,
        repo_kind=body.repo_kind,
        revision=body.revision,
    )
    if db.get(User, user_id) is None:
        raise DomainError("NOT_FOUND", "Owner not found", 404)
    port = provider or repository_provider(reference.provider_key)
    if port.provider_key != reference.provider_key:
        raise DomainError(
            "PROVIDER_MISMATCH", "Repository provider differs from the selected source", 409
        )
    result = await port.get_repository(reference)
    try:
        candidate = schema.RepositoryCandidateSnapshot.model_validate(asdict(result))
    except ValidationError as error:
        raise DomainError(
            "SOURCE_METADATA_INVALID", "Provider returned invalid public metadata", 422
        ) from error
    if (candidate.provider_key, candidate.repo_kind, candidate.repo_id) != (
        reference.provider_key,
        reference.repo_kind,
        reference.repo_id,
    ):
        raise DomainError(
            "SOURCE_IDENTITY_MISMATCH", "Provider returned a different repository identity", 409
        )
    canonical = normalize_repository_ref(
        candidate.canonical_url, provider_key=candidate.provider_key, repo_kind=candidate.repo_kind
    )
    if canonical.repo_id != candidate.repo_id:
        raise DomainError(
            "SOURCE_IDENTITY_MISMATCH",
            "Canonical repository address differs from its identity",
            409,
        )
    if candidate.readme_text is None:
        if candidate.readme_sha256 is not None:
            raise DomainError(
                "SOURCE_METADATA_INVALID", "Missing card has a contradictory hash", 422
            )
    elif (
        hashlib.sha256(candidate.readme_text.encode("utf-8")).hexdigest() != candidate.readme_sha256
    ):
        raise DomainError(
            "SOURCE_METADATA_INVALID", "Repository card hash differs from its text", 422
        )
    payload = candidate.model_dump(mode="json")
    snapshot_sha256 = _hash_payload(payload)
    raw_bytes = json.dumps(candidate.raw_metadata, ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )
    if len(raw_bytes) > MAX_RAW_METADATA_BYTES:
        raise DomainError(
            "SOURCE_METADATA_TOO_LARGE", "Raw repository metadata exceeds its audit bound", 413
        )
    preview = RepositoryImportPreview(
        user_id=user_id,
        provider_key=candidate.provider_key,
        repo_kind=candidate.repo_kind,
        repo_id=candidate.repo_id,
        provider_id=candidate.provider_id,
        requested_revision=reference.revision,
        canonical_url=candidate.canonical_url,
        source_hash=candidate.source_hash,
        snapshot_sha256=snapshot_sha256,
        candidate_payload=payload,
    )
    db.add(preview)
    db.commit()
    db.refresh(preview)
    return preview


def _target(
    db: Session, user_id: uuid.UUID, kind: str, entity_id: uuid.UUID
) -> CodeRepository | Model | Dataset:
    models: dict[str, type[CodeRepository] | type[Model] | type[Dataset]] = {
        "code_repository": CodeRepository,
        "model": Model,
        "dataset": Dataset,
    }
    model = models[kind]
    entity = db.scalar(
        select(ResearchEntity).where(
            ResearchEntity.id == entity_id,
            ResearchEntity.user_id == user_id,
            ResearchEntity.kind == kind,
            ResearchEntity.deleted_at.is_(None),
        )
    )
    if entity is None:
        raise DomainError("NOT_FOUND", "Registry target not found for this owner and kind", 404)
    return registry.owned(db, user_id, model, entity_id)


def _assert_code_target(record: CodeRepository, candidate: schema.RepositoryCandidateOut) -> None:
    from app.domain.repository_identity import normalize_repository_ref

    if record.provider_key is not None and record.provider_key != candidate.provider_key:
        raise DomainError(
            "SOURCE_TARGET_MISMATCH", "Existing repository belongs to a different provider", 409
        )
    if record.external_id is not None and record.external_id != candidate.provider_id:
        raise DomainError(
            "SOURCE_TARGET_MISMATCH", "Existing repository has a different external identity", 409
        )
    if record.url is not None:
        try:
            current = normalize_repository_ref(
                record.url, provider_key=candidate.provider_key, repo_kind=candidate.repo_kind
            )
        except DomainError as error:
            raise DomainError(
                "SOURCE_TARGET_MISMATCH",
                "Existing repository address cannot be matched to this source",
                409,
            ) from error
        if current.repo_id != candidate.repo_id:
            raise DomainError(
                "SOURCE_TARGET_MISMATCH", "Existing repository address differs from the source", 409
            )


def _new_binding(
    db: Session,
    user_id: uuid.UUID,
    candidate: schema.RepositoryCandidateOut,
    body: schema.RepositoryConfirmRequest,
) -> RepositoryBinding:
    kind = TARGET_KIND[candidate.repo_kind]
    name = body.name or candidate.name
    if body.existing_entity_id is None and (not name.strip() or len(name) > 240):
        raise DomainError(
            "REGISTRY_NAME_REQUIRED", "Provide a registry name with 1 to 240 characters", 422
        )
    if body.existing_entity_id is not None:
        target = _target(db, user_id, kind, body.existing_entity_id)
        if isinstance(target, CodeRepository):
            _assert_code_target(target, candidate)
    elif kind == "code_repository":
        target = registry.create_repository(
            db,
            user_id,
            experiment_schema.CodeRepositoryCreate(
                name=name,
                provider_key=candidate.provider_key,
                external_id=candidate.provider_id,
                url=candidate.canonical_url,
            ),
            commit=False,
        )
    else:
        if body.task is None or not body.task.strip():
            raise DomainError(
                "RESEARCH_TASK_REQUIRED",
                "Select the scientific task before creating a registry entry",
                422,
            )
        values = {
            "name": name,
            "task": body.task,
            "modalities": body.modalities or [],
            "source": candidate.canonical_url,
        }
        if kind == "model":
            created = registry.create_registry(
                db, user_id, experiment_schema.ModelCreate(**values), commit=False
            )
        else:
            created = registry.create_registry(
                db,
                user_id,
                experiment_schema.DatasetCreate(
                    **values, license=candidate.license_id, description=candidate.description
                ),
                commit=False,
            )
        target = created
    code_id = target.id if isinstance(target, CodeRepository) else None
    if kind == "model":
        code = registry.create_repository(
            db,
            user_id,
            experiment_schema.CodeRepositoryCreate(
                name=target.name,
                provider_key=candidate.provider_key,
                external_id=candidate.provider_id,
                url=candidate.canonical_url,
            ),
            commit=False,
        )
        code_id = code.id
    binding = RepositoryBinding(
        user_id=user_id,
        provider_key=candidate.provider_key,
        repo_kind=candidate.repo_kind,
        repo_id=candidate.repo_id,
        provider_id=candidate.provider_id,
        entity_id=target.id,
        entity_kind=kind,
        code_repository_id=code_id,
    )
    db.add(binding)
    db.flush()
    return binding


def confirm_preview(
    db: Session, user_id: uuid.UUID, preview_id: uuid.UUID, body: schema.RepositoryConfirmRequest
) -> RepositoryImportPreview:
    # Serialise identity adoption under the installation's owner, including
    # autoflush=False callers. Every registry/source/event write commits once.
    if db.scalar(select(User.id).where(User.id == user_id).with_for_update()) is None:
        raise DomainError("NOT_FOUND", "Owner not found", 404)
    preview = get_preview(db, user_id, preview_id, lock=True)
    candidate = _candidate(preview)
    if (preview.provider_key, preview.repo_kind, preview.repo_id, preview.provider_id) != (
        candidate.provider_key,
        candidate.repo_kind,
        candidate.repo_id,
        candidate.provider_id,
    ):
        raise DomainError(
            "INVALID_SOURCE_SNAPSHOT", "Preview identity differs from its frozen receipt", 409
        )
    if body.expected_source_hash != preview.source_hash:
        raise DomainError(
            "SOURCE_HASH_MISMATCH", "Preview source hash changed; inspect the frozen preview", 409
        )
    if preview.status == "CONFIRMED":
        confirmed_source = registry.owned(
            db, user_id, RepositorySourceSnapshot, cast(uuid.UUID, preview.confirmed_snapshot_id)
        )
        confirmed_binding = registry.owned(
            db, user_id, RepositoryBinding, confirmed_source.binding_id
        )
        if confirmed_source.source_hash != preview.source_hash or (
            confirmed_binding.provider_key,
            confirmed_binding.repo_kind,
            confirmed_binding.repo_id,
            confirmed_binding.provider_id,
        ) != (preview.provider_key, preview.repo_kind, preview.repo_id, preview.provider_id):
            raise DomainError(
                "INVALID_SOURCE_SNAPSHOT",
                "Confirmed source differs from the frozen preview identity",
                409,
            )
        _candidate(confirmed_source)
        if (
            body.existing_entity_id is not None
            and body.existing_entity_id != confirmed_source.entity_id
        ):
            raise DomainError(
                "BINDING_TARGET_CONFLICT",
                "This preview was already confirmed to a different target",
                409,
            )
        return preview
    binding, conflict = _binding_match(db, user_id, candidate)
    if conflict:
        raise DomainError(
            "REPOSITORY_IDENTITY_CONFLICT",
            "Repository name and provider identity conflict with a prior binding",
            409,
        )
    if (
        binding is not None
        and body.existing_entity_id is not None
        and body.existing_entity_id != binding.entity_id
    ):
        raise DomainError(
            "BINDING_TARGET_CONFLICT",
            "This source is already bound to a different registry target",
            409,
        )
    try:
        binding = binding or _new_binding(db, user_id, candidate, body)
        _target(db, user_id, binding.entity_kind, binding.entity_id)
        source = db.scalar(
            select(RepositorySourceSnapshot).where(
                RepositorySourceSnapshot.user_id == user_id,
                RepositorySourceSnapshot.binding_id == binding.id,
                RepositorySourceSnapshot.source_hash == candidate.source_hash,
            )
        )
        if source is None:
            model_version_id = dataset_version_id = None
            version = "remote-" + candidate.source_hash
            if binding.entity_kind == "model":
                model_version = registry.create_model_version(
                    db,
                    user_id,
                    binding.entity_id,
                    experiment_schema.ModelVersionCreate(
                        version=version,
                        code_repository_id=binding.code_repository_id,
                        git_commit=candidate.commit_sha,
                    ),
                    commit=False,
                )
                model_version_id = model_version.id
            elif binding.entity_kind == "dataset":
                dataset_version = registry.create_dataset_version(
                    db,
                    user_id,
                    binding.entity_id,
                    experiment_schema.DatasetVersionCreate(
                        version=version,
                        locations=[
                            experiment_schema.DatasetLocationCreate(
                                storage_provider=candidate.provider_key,
                                uri=candidate.canonical_url
                                + "#revision="
                                + (candidate.commit_sha or candidate.source_hash),
                                mount_hint="Remote metadata reference; no data downloaded",
                            )
                        ],
                    ),
                    commit=False,
                )
                dataset_version_id = dataset_version.id
            source = RepositorySourceSnapshot(
                user_id=user_id,
                binding_id=binding.id,
                entity_id=binding.entity_id,
                entity_kind=binding.entity_kind,
                model_version_id=model_version_id,
                dataset_version_id=dataset_version_id,
                source_hash=candidate.source_hash,
                snapshot_sha256=preview.snapshot_sha256,
                requested_revision=preview.requested_revision,
                canonical_url=candidate.canonical_url,
                commit_sha=candidate.commit_sha,
                candidate_payload=preview.candidate_payload,
            )
            db.add(source)
            db.flush()
        else:
            previous_candidate = _candidate(source)
            # Fetch time and warnings may differ for the same upstream receipt;
            # actual commit/card/source identity cannot be silently repointed.
            if (
                previous_candidate.commit_sha != candidate.commit_sha
                or previous_candidate.readme_sha256 != candidate.readme_sha256
                or previous_candidate.canonical_url != candidate.canonical_url
            ):
                raise DomainError(
                    "SOURCE_VERSION_CONFLICT",
                    "An existing source hash has contradictory commit or card metadata",
                    409,
                )
        preview.status, preview.confirmed_snapshot_id, preview.confirmed_at = (
            "CONFIRMED",
            source.id,
            datetime.now(UTC),
        )
        db.add(
            ResearchEvent(
                event_id=uuid.uuid4(),
                user_id=user_id,
                event_type="repository.import_confirmed",
                occurred_at=datetime.now(UTC),
                source="owner",
                payload={
                    "entity_kind": binding.entity_kind,
                    "entity_id": str(binding.entity_id),
                    "preview_id": str(preview.id),
                    "binding_id": str(binding.id),
                    "source_snapshot_id": str(source.id),
                    "source_hash": source.source_hash,
                    "model_version_id": str(source.model_version_id)
                    if source.model_version_id
                    else None,
                    "dataset_version_id": str(source.dataset_version_id)
                    if source.dataset_version_id
                    else None,
                },
            )
        )
        db.commit()
        db.refresh(preview)
        return preview
    except IntegrityError as error:
        db.rollback()
        raise DomainError(
            "REPOSITORY_IMPORT_CONFLICT",
            "Registry or source identity already exists; inspect the existing target",
            409,
        ) from error
    except Exception:
        db.rollback()
        raise


def binding_out(
    db: Session, user_id: uuid.UUID, binding: RepositoryBinding
) -> schema.RepositoryBindingOut:
    target = _target(db, user_id, binding.entity_kind, binding.entity_id)
    scientific = (
        registry.registry_out(db, user_id, target) if isinstance(target, (Dataset, Model)) else None
    )
    return schema.RepositoryBindingOut.model_validate(
        {
            "id": binding.id,
            "provider_key": binding.provider_key,
            "repo_kind": binding.repo_kind,
            "repo_id": binding.repo_id,
            "provider_id": binding.provider_id,
            "entity_id": binding.entity_id,
            "entity_kind": binding.entity_kind,
            "code_repository_id": binding.code_repository_id,
            "entity_name": target.name,
            "task": scientific.task if scientific else None,
            "modalities": scientific.modalities if scientific else [],
            "created_at": binding.created_at,
        }
    )


def source_out(db: Session, user_id: uuid.UUID, source_id: uuid.UUID) -> schema.RepositorySourceOut:
    source = registry.owned(db, user_id, RepositorySourceSnapshot, source_id)
    binding = registry.owned(db, user_id, RepositoryBinding, source.binding_id)
    candidate = _candidate(source)
    if (candidate.provider_key, candidate.repo_kind, candidate.repo_id, candidate.provider_id) != (
        binding.provider_key,
        binding.repo_kind,
        binding.repo_id,
        binding.provider_id,
    ) or candidate.commit_sha != source.commit_sha:
        raise DomainError(
            "INVALID_SOURCE_SNAPSHOT", "Source identity differs from its normalized binding", 409
        )
    return schema.RepositorySourceOut.model_validate(
        {
            "id": source.id,
            "binding_id": binding.id,
            "target_entity_id": source.entity_id,
            "target_entity_kind": source.entity_kind,
            "provider_key": binding.provider_key,
            "repo_kind": binding.repo_kind,
            "repo_id": binding.repo_id,
            "provider_id": binding.provider_id,
            "source_hash": source.source_hash,
            "snapshot_sha256": source.snapshot_sha256,
            "revision": source.requested_revision,
            "canonical_url": source.canonical_url,
            "commit_sha": source.commit_sha,
            "model_version_id": source.model_version_id,
            "dataset_version_id": source.dataset_version_id,
            "code_repository_id": binding.code_repository_id,
            "created_at": source.created_at,
            "candidate": schema.RepositoryCandidateOut.model_validate(candidate),
        }
    )


def preview_out(
    db: Session, user_id: uuid.UUID, preview: RepositoryImportPreview
) -> schema.RepositoryImportOut:
    candidate = _candidate(preview)
    binding, conflict = _binding_match(db, user_id, candidate)
    warnings = list(candidate.warnings)
    if binding is not None:
        warnings.append(
            "HUMAN_METADATA_PRESERVED: existing target name/task/modalities and repository fields are preserved."
        )
    if conflict:
        warnings.append(
            "REPOSITORY_IDENTITY_CONFLICT: confirmation needs a manual identity decision."
        )
    if candidate.commit_sha is None:
        warnings.append(
            "SOURCE_REVISION_UNKNOWN: no immutable commit was reported by the provider."
        )
    source = (
        source_out(db, user_id, preview.confirmed_snapshot_id)
        if preview.confirmed_snapshot_id is not None
        else None
    )
    return schema.RepositoryImportOut.model_validate(
        {
            "id": preview.id,
            "provider_key": preview.provider_key,
            "repo_kind": preview.repo_kind,
            "repo_id": preview.repo_id,
            "provider_id": preview.provider_id,
            "revision": preview.requested_revision,
            "canonical_url": preview.canonical_url,
            "source_hash": preview.source_hash,
            "snapshot_sha256": preview.snapshot_sha256,
            "status": preview.status,
            "created_at": preview.created_at,
            "confirmed_at": preview.confirmed_at,
            "candidate": schema.RepositoryCandidateOut.model_validate(candidate),
            "existing_binding": binding_out(db, user_id, binding) if binding is not None else None,
            "target_entity_id": source.target_entity_id if source else None,
            "target_entity_kind": source.target_entity_kind if source else None,
            "model_version_id": source.model_version_id if source else None,
            "dataset_version_id": source.dataset_version_id if source else None,
            "code_repository_id": source.code_repository_id if source else None,
            "source_snapshot_id": source.id if source else None,
            "warnings": warnings,
        }
    )


def list_previews(
    db: Session, user_id: uuid.UUID, limit: int, offset: int
) -> schema.RepositoryImportPage:
    count = (
        db.scalar(
            select(func.count())
            .select_from(RepositoryImportPreview)
            .where(RepositoryImportPreview.user_id == user_id)
        )
        or 0
    )
    rows = db.scalars(
        select(RepositoryImportPreview)
        .where(RepositoryImportPreview.user_id == user_id)
        .order_by(RepositoryImportPreview.created_at.desc(), RepositoryImportPreview.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return schema.RepositoryImportPage(
        items=[preview_out(db, user_id, row) for row in rows],
        total=count,
        limit=limit,
        offset=offset,
    )
