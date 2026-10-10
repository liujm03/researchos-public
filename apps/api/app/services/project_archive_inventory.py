"""Register source-proven project archive versions without Git or upload writes."""

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.archive_catalog import ArchiveCatalogProvider, ArchiveCatalogSnapshot
from app.domain.github_archive import GitHubPrivateRepository, ProjectArchiveProvider
from app.errors import DomainError
from app.models_project_archives import (
    ProjectArchiveBinding,
    ProjectArchiveFile,
    ProjectArchiveVersion,
)
from app.providers.registry import archive_catalog, archive_catalog_workspaces, archive_remote
from app.schemas_project_archives import (
    ArchiveBindingOut,
    ArchiveFileOut,
    ArchiveInventoryOut,
    ArchiveStatusOut,
    ArchiveVersionOut,
    ArchiveWorkspaceOut,
)
from app.services.projects import get_project


def capability() -> ArchiveStatusOut:
    settings = get_settings()
    configured = archive_catalog_workspaces()
    enabled = settings.project_archive_catalog_enabled
    return ArchiveStatusOut(
        enabled=enabled,
        write_enabled=settings.project_archive_write_enabled,
        write_detail="已允许已绑定范围内的后台代码版本与私有推送。" if settings.project_archive_write_enabled else "执行主机未启用后台归档写入；历史版本仍可查看。",
        workspaces=[
            ArchiveWorkspaceOut(key=key, label=value[0]) for key, value in configured.items()
        ],
        detail="已启用既有归档只读接入，账户与私有版本将在接入时实际核验。"
        if enabled
        else "执行主机尚未启用归档接入；现有版本记录仍可查看。",
    )


def inventory(db: Session, user_id: uuid.UUID, project_id: uuid.UUID) -> ArchiveInventoryOut:
    get_project(db, user_id, project_id)
    binding = db.scalar(
        select(ProjectArchiveBinding).where(
            ProjectArchiveBinding.user_id == user_id, ProjectArchiveBinding.project_id == project_id
        )
    )
    if binding is None:
        return ArchiveInventoryOut(binding=None, versions=[])
    rows = db.scalars(
        select(ProjectArchiveVersion)
        .where(
            ProjectArchiveVersion.user_id == user_id, ProjectArchiveVersion.binding_id == binding.id
        )
        .order_by(ProjectArchiveVersion.created_at.desc(), ProjectArchiveVersion.tag)
    )
    versions = [
        ArchiveVersionOut.model_validate(
            {
                **{
                    key: getattr(row, key)
                    for key in ArchiveVersionOut.model_fields
                    if key != "status"
                },
                "status": "VERIFIED_REMOTE" if row.remote_tag_commit is not None else "LOCAL_ONLY",
            }
        )
        for row in rows
    ]
    return ArchiveInventoryOut(binding=ArchiveBindingOut.model_validate(binding), versions=versions)


def version_files(
    db: Session, user_id: uuid.UUID, project_id: uuid.UUID, version_id: uuid.UUID
) -> list[ArchiveFileOut]:
    get_project(db, user_id, project_id)
    version = db.scalar(
        select(ProjectArchiveVersion)
        .join(ProjectArchiveBinding, ProjectArchiveVersion.binding_id == ProjectArchiveBinding.id)
        .where(
            ProjectArchiveVersion.id == version_id,
            ProjectArchiveVersion.user_id == user_id,
            ProjectArchiveBinding.user_id == user_id,
            ProjectArchiveBinding.project_id == project_id,
        )
    )
    if version is None:
        raise DomainError("NOT_FOUND", "Archive version not found in this project", 404)
    rows = db.scalars(
        select(ProjectArchiveFile)
        .where(ProjectArchiveFile.version_id == version_id, ProjectArchiveFile.user_id == user_id)
        .order_by(ProjectArchiveFile.path)
    )
    return [ArchiveFileOut.model_validate(row) for row in rows]


def _identity(repository: GitHubPrivateRepository) -> tuple[str, int, str, int]:
    return (
        repository.owner_login.casefold(),
        repository.owner_id,
        repository.name.casefold(),
        repository.repository_id,
    )


def _validate_source(source: ArchiveCatalogSnapshot) -> None:
    if (
        not source.local_project_id
        or len(source.local_project_id) > 160
        or len(source.versions) > 100
    ):
        raise DomainError(
            "ARCHIVE_CATALOG_INVALID",
            "Archive source must contain a bounded complete version inventory",
            409,
        )
    seen: set[str] = set()
    for entry in source.versions:
        receipt, manifest = entry.receipt, entry.manifest
        if (
            receipt.owner_id != "github:" + str(source.repository.owner_id)
            or receipt.project_id != source.local_project_id
            or manifest.owner_id != receipt.owner_id
            or manifest.project_id != receipt.project_id
            or manifest.version != receipt.tag
            or receipt.version != receipt.tag
            or manifest.sha256 != receipt.manifest_sha256
            or receipt.tag in seen
            or len(receipt.tag) > 120
            or len(manifest.files) > 2000
            or any(len(row.path) > 1024 for row in manifest.files)
            or len({row.path for row in manifest.files}) != len(manifest.files)
        ):
            raise DomainError(
                "ARCHIVE_CATALOG_INVALID", "Frozen source version identity is inconsistent", 409
            )
        seen.add(receipt.tag)


async def import_inventory(
    db: Session,
    user_id: uuid.UUID,
    project_id: uuid.UUID,
    workspace_key: str,
    *,
    catalog: ArchiveCatalogProvider | None = None,
    remote: ProjectArchiveProvider | None = None,
) -> ArchiveInventoryOut:
    get_project(db, user_id, project_id)
    registered = db.scalar(select(ProjectArchiveBinding).where(ProjectArchiveBinding.user_id == user_id, ProjectArchiveBinding.project_id == project_id))
    if catalog is not None:
        local = catalog
    elif registered is not None and registered.managed_folder_name is not None:
        if workspace_key != registered.workspace_key:
            raise DomainError("ARCHIVE_BINDING_CONFLICT", "Managed project key differs from its approved binding", 409)
        local = archive_catalog(workspace_key, managed_folder_name=registered.managed_folder_name, managed_root_fingerprint=registered.managed_root_fingerprint)
    else:
        local = archive_catalog(workspace_key)
    source = await asyncio.to_thread(local.snapshot)
    _validate_source(source)
    provider = (
        remote
        if remote is not None
        else await asyncio.to_thread(archive_remote, source.repository.owner_login)
    )
    account = await provider.inspect_authenticated_account(
        source.repository.owner_login, source.repository.owner_id
    )
    verified = await provider.get_private_owned_repository(
        source.repository.owner_login,
        source.repository.name,
        expected_owner_id=source.repository.owner_id,
        expected_repository_id=source.repository.repository_id,
    )
    if (
        (account.login.casefold(), account.user_id) != _identity(source.repository)[:2]
        or _identity(verified) != _identity(source.repository)
        or verified.private is not True
        or verified.push_allowed is not True
    ):
        raise DomainError(
            "ARCHIVE_DESTINATION_CHANGED",
            "Execution account or private repository differs from the source binding",
            409,
        )
    now = datetime.now(UTC)
    observed: dict[str, str | None] = {}
    for entry in source.versions:
        ref = await provider.inspect_ref(verified, "tags/" + entry.receipt.tag)
        if ref is not None and (
            ref.object_type != "commit"
            or ref.sha != entry.receipt.commit_sha
            or ref.ref != "tags/" + entry.receipt.tag
        ):
            raise DomainError(
                "ARCHIVE_REMOTE_VERSION_CONFLICT",
                "Remote immutable tag differs from the exact local version",
                409,
            )
        observed[entry.receipt.tag] = None if ref is None else ref.sha

    binding = db.scalar(
        select(ProjectArchiveBinding).where(
            ProjectArchiveBinding.user_id == user_id, ProjectArchiveBinding.project_id == project_id
        )
    )
    if binding is not None and (
        binding.workspace_key != workspace_key
        or binding.local_project_id != source.local_project_id
        or (
            binding.github_owner.casefold(),
            binding.github_owner_id,
            binding.github_repository.casefold(),
            binding.github_repository_id,
        )
        != _identity(verified)
    ):
        raise DomainError(
            "ARCHIVE_BINDING_CONFLICT",
            "Existing project destination cannot be silently replaced",
            409,
        )
    if binding is None:
        other = db.scalar(
            select(ProjectArchiveBinding).where(
                ProjectArchiveBinding.user_id == user_id,
                (ProjectArchiveBinding.workspace_key == workspace_key)
                | (ProjectArchiveBinding.github_repository_id == verified.repository_id),
            )
        )
        if other is not None:
            raise DomainError(
                "ARCHIVE_BINDING_CONFLICT",
                "Workspace or repository is already bound to another project",
                409,
            )
        binding = ProjectArchiveBinding(
            user_id=user_id,
            project_id=project_id,
            workspace_key=workspace_key,
            local_project_id=source.local_project_id,
            github_owner=verified.owner_login,
            github_owner_id=verified.owner_id,
            github_repository=verified.name,
            github_repository_id=verified.repository_id,
            verified_at=now,
        )
    existing = (
        {
            row.tag: row
            for row in db.scalars(
                select(ProjectArchiveVersion).where(
                    ProjectArchiveVersion.user_id == user_id,
                    ProjectArchiveVersion.binding_id == binding.id,
                )
            )
        }
        if binding.id is not None
        else {}
    )
    if set(existing) - set(observed):
        raise DomainError(
            "ARCHIVE_LOCAL_HISTORY_CHANGED",
            "Previously registered local version receipts are missing; retained history is preserved",
            409,
        )
    for entry in source.versions:
        row = existing.get(entry.receipt.tag)
        if row is None:
            continue
        manifest = entry.manifest
        if (
            row.commit_sha,
            row.manifest_sha256,
            row.parent_commit,
            row.file_count,
            row.total_bytes,
        ) != (
            entry.receipt.commit_sha,
            manifest.sha256,
            manifest.parent_commit,
            len(manifest.files),
            sum(file.size_bytes for file in manifest.files),
        ):
            raise DomainError(
                "ARCHIVE_LOCAL_VERSION_CONFLICT",
                "Previously registered immutable version differs",
                409,
            )
        retained = {
            (file.path, file.sha256, file.size_bytes)
            for file in db.scalars(
                select(ProjectArchiveFile).where(
                    ProjectArchiveFile.version_id == row.id, ProjectArchiveFile.user_id == user_id
                )
            )
        }
        if retained != {(file.path, file.sha256, file.size_bytes) for file in manifest.files}:
            raise DomainError(
                "ARCHIVE_LOCAL_VERSION_CONFLICT", "Previously registered file manifest differs", 409
            )
        if row.remote_tag_commit is not None and observed[row.tag] != row.remote_tag_commit:
            raise DomainError(
                "ARCHIVE_REMOTE_HISTORY_CHANGED",
                "Previously verified remote tag is missing; retained evidence is preserved",
                409,
            )
    # Complete network/source verification precedes every registry write.
    try:
        db.add(binding)
        binding.verified_at = now
        db.flush()
        for entry in source.versions:
            receipt, manifest = entry.receipt, entry.manifest
            row = existing.get(receipt.tag)
            if row is None:
                row = ProjectArchiveVersion(
                    user_id=user_id,
                    binding_id=binding.id,
                    tag=receipt.tag,
                    commit_sha=receipt.commit_sha,
                    manifest_sha256=manifest.sha256,
                    parent_commit=manifest.parent_commit,
                    file_count=len(manifest.files),
                    total_bytes=sum(file.size_bytes for file in manifest.files),
                )
                db.add(row)
                db.flush()
                db.add_all(
                    [
                        ProjectArchiveFile(
                            version_id=row.id,
                            user_id=user_id,
                            path=file.path,
                            sha256=file.sha256,
                            size_bytes=file.size_bytes,
                        )
                        for file in manifest.files
                    ]
                )
            if observed[receipt.tag] is not None:
                row.remote_tag_commit = observed[receipt.tag]
                row.remote_verified_at = now
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError(
            "ARCHIVE_REGISTRY_CONFLICT",
            "Another binding or version update conflicts; refresh existing inventory",
            409,
        ) from None
    return inventory(db, user_id, project_id)
