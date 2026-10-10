"""Explicit owner approval freezes data; saves never authorize scientific execution."""

import hashlib
import io
import json
import re
import uuid
import zipfile
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.idea_handoff import idea_source_file
from app.domain.server_packages import ServerPackageRenderedBundle
from app.errors import DomainError
from app.models import Attachment, ResearchEntity, Task
from app.models_project_archives import (
    ProjectArchiveBinding,
    ProjectArchiveFile,
    ProjectArchiveVersion,
)
from app.models_research_briefs import ResearchBrief, ResearchBriefReview
from app.models_server_task_packages import (
    ServerTaskPackage,
    ServerTaskPackageAsset,
    ServerTaskPackageExpectedArtifact,
    ServerTaskPackageFile,
    ServerTaskPackageSaveAttempt,
    ServerTaskPackageTask,
)
from app.providers import registry
from app.schemas import PageMeta
from app.schemas_server_task_packages import (
    ServerPackageArchiveOption,
    ServerPackageBriefOption,
    ServerPackageFileOut,
    ServerPackageSaveAttemptOut,
    ServerTaskPackageCreateRequest,
    ServerTaskPackageOptions,
    ServerTaskPackageOut,
    ServerTaskPackagePreviewOut,
    ServerTaskPackageRetryRequest,
    ServerTaskPackageSelection,
    ServerTaskPackageSummary,
)
from app.services import research_briefs as briefs
from app.services.common import decode_cursor, encode_cursor
from app.services.projects import get_project

SCOPE_NOTE = "LOCAL_ONLY：本包仅为本人声明的服务器交接材料，不执行命令、不提交作业、不授予科研执行权限。代码只引用登记版本；依赖、数据和资源待服务器核验。"
MAX_BYTES = 2 * 1024 * 1024


def _error(code: str, message: str, status: int = 409) -> DomainError:
    return DomainError(code, message, status)


def _fresh(db: Session) -> None:
    db.expire_all()


def _source(
    db: Session,
    owner: uuid.UUID,
    project_id: uuid.UUID,
    selection: ServerTaskPackageSelection,
    *,
    lock: bool = False,
) -> tuple[dict[str, Any], str, list[str]]:
    if lock:
        from app.models import Paper, ResearchProject
        from app.models_research_briefs import ResearchBriefEvidence, ResearchBriefSection

        db.scalar(
            select(ResearchProject)
            .where(ResearchProject.id == project_id, ResearchProject.user_id == owner)
            .with_for_update()
        )
        db.scalar(
            select(ResearchBrief)
            .where(
                ResearchBrief.id == selection.brief_id,
                ResearchBrief.user_id == owner,
                ResearchBrief.project_id == project_id,
            )
            .with_for_update()
        )
        db.scalar(
            select(ResearchBriefReview)
            .where(
                ResearchBriefReview.brief_id == selection.brief_id,
                ResearchBriefReview.user_id == owner,
            )
            .with_for_update()
        )
        list(
            db.scalars(
                select(ResearchBriefSection)
                .where(
                    ResearchBriefSection.brief_id == selection.brief_id,
                    ResearchBriefSection.user_id == owner,
                )
                .with_for_update()
            )
        )
        evidence = list(
            db.scalars(
                select(ResearchBriefEvidence)
                .where(
                    ResearchBriefEvidence.brief_id == selection.brief_id,
                    ResearchBriefEvidence.user_id == owner,
                )
                .with_for_update()
            )
        )
        if evidence:
            list(
                db.scalars(
                    select(Paper)
                    .where(Paper.id.in_([x.paper_id for x in evidence]), Paper.user_id == owner)
                    .with_for_update()
                )
            )
        if selection.archive_version_id:
            version = db.scalar(
                select(ProjectArchiveVersion)
                .where(
                    ProjectArchiveVersion.id == selection.archive_version_id,
                    ProjectArchiveVersion.user_id == owner,
                )
                .with_for_update()
            )
            if version:
                db.scalar(
                    select(ProjectArchiveBinding)
                    .where(
                        ProjectArchiveBinding.id == version.binding_id,
                        ProjectArchiveBinding.user_id == owner,
                    )
                    .with_for_update()
                )
                list(
                    db.scalars(
                        select(ProjectArchiveFile)
                        .where(
                            ProjectArchiveFile.version_id == version.id,
                            ProjectArchiveFile.user_id == owner,
                        )
                        .with_for_update()
                    )
                )
    project = get_project(db, owner, project_id)
    row = briefs.get_brief(db, owner, project_id, selection.brief_id)
    detail = briefs.detail_out(db, row)
    if not briefs._intact(db, row) or not detail.context_current or detail.status != "ACCEPTED":
        raise _error(
            "SERVER_PACKAGE_BRIEF_INELIGIBLE",
            "Require an intact, current, owner-accepted brief exact matching acceptance",
        )
    review = db.scalar(
        select(ResearchBriefReview).where(
            ResearchBriefReview.brief_id == row.id,
            ResearchBriefReview.user_id == owner,
            ResearchBriefReview.project_id == project_id,
        )
    )
    if (
        review is None
        or review.decision != "ACCEPT"
        or review.sha256 != row.sha256
        or review.reviewer_id != owner
    ):
        raise _error("SERVER_PACKAGE_REVIEW_INVALID", "The exact brief acceptance is unavailable")
    sections = briefs._sections(db, row)
    gaps = ["MISSING_" + section.key.upper() for section in sections if not section.content]
    if not row.stop_rules:
        gaps.append("STOP_RULES_NOT_DEFINED")
    gaps.extend(
        name
        for name, value in (
            ("CODE_VERSION_NOT_SELECTED", selection.archive_version_id),
            ("RUN_INSTRUCTIONS_NOT_DECLARED", selection.run_instructions),
            ("RESOURCE_LIMITS_NOT_DECLARED", selection.resource_limits),
            (
                "DEPENDENCIES_NOT_DECLARED",
                any(x.role == "DEPENDENCIES" for x in selection.materials),
            ),
            ("CONFIG_NOT_DECLARED", any(x.role == "CONFIG" for x in selection.materials)),
            ("ASSET_REFERENCES_NOT_DECLARED", selection.assets),
            ("EXPECTED_ARTIFACTS_NOT_DECLARED", selection.expected_artifacts),
        )
        if not value
    )
    archive = None
    if selection.archive_version_id is not None:
        version = db.scalar(
            select(ProjectArchiveVersion)
            .join(
                ProjectArchiveBinding, ProjectArchiveBinding.id == ProjectArchiveVersion.binding_id
            )
            .where(
                ProjectArchiveVersion.id == selection.archive_version_id,
                ProjectArchiveVersion.user_id == owner,
                ProjectArchiveBinding.user_id == owner,
                ProjectArchiveBinding.project_id == project_id,
            )
        )
        if version is None:
            raise _error("NOT_FOUND", "Owned project archive version not found", 404)
        binding = db.get(ProjectArchiveBinding, version.binding_id)
        files = list(
            db.scalars(
                select(ProjectArchiveFile)
                .where(
                    ProjectArchiveFile.version_id == version.id, ProjectArchiveFile.user_id == owner
                )
                .order_by(ProjectArchiveFile.path)
            )
        )
        if (
            binding is None
            or len(files) != version.file_count
            or sum(x.size_bytes for x in files) != version.total_bytes
            or not re.fullmatch(r"[0-9a-f]{40}", version.commit_sha)
            or not re.fullmatch(r"[0-9a-f]{64}", version.manifest_sha256)
            or any(x.size_bytes < 0 or not re.fullmatch(r"[0-9a-f]{64}", x.sha256) for x in files)
        ):
            raise _error("SERVER_PACKAGE_ARCHIVE_INVALID", "Recorded code manifest is inconsistent")
        archive = {
            "binding": {
                "id": str(binding.id),
                "repository": binding.github_owner + "/" + binding.github_repository,
                "repository_id": binding.github_repository_id,
                "owner_id": binding.github_owner_id,
                "verified_at": str(binding.verified_at),
            },
            "version": {
                "id": str(version.id),
                "tag": version.tag,
                "commit_sha": version.commit_sha,
                "manifest_sha256": version.manifest_sha256,
                "file_count": version.file_count,
                "total_bytes": version.total_bytes,
                "remote_tag_commit": version.remote_tag_commit,
                "remote_verified_at": str(version.remote_verified_at)
                if version.remote_verified_at
                else None,
            },
            "files": [
                {"path": x.path, "sha256": x.sha256, "size_bytes": x.size_bytes} for x in files
            ],
        }
    brief_snapshot = detail.model_dump(mode="json")
    if not detail.canonical_note_sources:
        brief_snapshot.pop("canonical_note_sources", None)
    if not detail.idea_sources:
        brief_snapshot.pop("idea_sources", None)
    manifest = {
        "owner_id": str(owner),
        "project": {"id": str(project_id), "name": project.name, "version": project.version},
        "brief": brief_snapshot,
        "review": {
            "sha256": review.sha256,
            "decision": review.decision,
            "reviewer_id": str(review.reviewer_id),
            "reviewed_at": str(review.reviewed_at),
            "comment": review.comment,
        },
        "archive": archive,
    }
    markdown = (
        "# 研究任务书\n\n"
        + row.idea
        + "\n\n"
        + "\n\n".join(
            "## "
            + x.key
            + "\n\n"
            + (x.content or "未填写")
            + "\n\n来源："
            + x.origin_type
            + ("\n\n不确定性：" + x.uncertainty if x.uncertainty else "")
            for x in sections
        )
        + "\n\n## 停止规则\n\n"
        + (row.stop_rules or "未定义；不得据此执行研究")
    )
    return manifest, markdown, gaps


def _verify_bundle(bundle: ServerPackageRenderedBundle) -> list[ServerPackageFileOut]:
    if (
        not isinstance(bundle.content, bytes)
        or not 0 < len(bundle.content) <= MAX_BYTES
        or bundle.sha256 != hashlib.sha256(bundle.content).hexdigest()
        or bundle.size_bytes != len(bundle.content)
    ):
        raise _error(
            "SERVER_PACKAGE_RENDER_INVALID", "Renderer bundle receipt differs from actual bytes"
        )
    files = []
    names = set()
    total = 0
    for item in bundle.files:
        path = item.path
        if (
            not isinstance(path, str)
            or path.startswith(("/", "\\"))
            or "\\" in path
            or ":" in path
            or any(x in {"", ".", ".."} for x in path.split("/"))
            or path.casefold() in names
        ):
            raise _error(
                "SERVER_PACKAGE_RENDER_INVALID", "Renderer supplied an unsafe or duplicate path"
            )
        names.add(path.casefold())
        raw = item.content.encode("utf-8")
        total += len(raw)
        if (
            len(raw) > MAX_BYTES
            or item.size_bytes != len(raw)
            or hashlib.sha256(raw).hexdigest() != item.sha256
        ):
            raise _error(
                "SERVER_PACKAGE_RENDER_INVALID", "Rendered file receipt differs from UTF-8 bytes"
            )
        files.append(
            ServerPackageFileOut(
                path=path,
                content=item.content,
                role=item.role,
                sha256=item.sha256,
                size_bytes=item.size_bytes,
            )
        )
    if not files or len(files) > 100 or total > MAX_BYTES:
        raise _error("SERVER_PACKAGE_RENDER_INVALID", "Rendered files exceed data package limits")
    try:
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            infos = archive.infolist()
            if (
                len(infos) != len(files)
                or {x.filename for x in infos} != {x.path for x in files}
                or any(
                    x.file_size > MAX_BYTES
                    or (
                        x.is_dir()
                        or ((x.external_attr >> 16) & 0o170000) not in (0, 0o100000)
                        or bool((x.external_attr >> 16) & 0o111)
                    )
                    for x in infos
                )
            ):
                raise ValueError("Invalid ZIP entries")
            for frozen_file in files:
                if archive.read(frozen_file.path) != frozen_file.content.encode("utf-8"):
                    raise ValueError("ZIP bytes differ")
    except (ValueError, zipfile.BadZipFile, KeyError, RuntimeError) as exc:
        raise _error(
            "SERVER_PACKAGE_RENDER_INVALID", "Actual ZIP differs from frozen files"
        ) from exc
    from app.domain.server_packages import SERVER_PACKAGE_FIXED_PATHS

    by_path = {item.path: item for item in files}
    if not SERVER_PACKAGE_FIXED_PATHS.issubset(by_path) or any(
        path not in SERVER_PACKAGE_FIXED_PATHS
        and not path.startswith("materials/")
        and not (
            re.fullmatch(r"ideas/[0-9a-f-]{36}\.md", path) and by_path[path].role == "IDEA_SOURCE"
        )
        and not (
            re.fullmatch(r"notes/[0-9a-f-]{36}\.md", path)
            and by_path[path].role == "CANONICAL_NOTE"
        )
        for path in by_path
    ):
        raise _error("SERVER_PACKAGE_RENDER_INVALID", "Renderer omitted required protocol files")
    try:
        receipt = json.loads(by_path["manifest.json"].content)
        if (
            not isinstance(receipt, dict)
            or receipt.get("contract") != "researchos-server-task-package-v1"
            or receipt.get("execution_authorized") is not False
            or receipt.get("delivery_status") != "LOCAL_ONLY"
            or receipt.get("code_bytes_included") is not False
        ):
            raise ValueError("Incorrect execution boundary")
        canonical_notes = (
            receipt.get("source_manifest", {}).get("brief", {}).get("canonical_note_sources", [])
        )
        expected_note_paths = set()
        for note in canonical_notes:
            path = "notes/" + str(note["canonical_note_id"]) + ".md"
            expected_note_paths.add(path)
            note_file = by_path[path]
            if (
                note_file.content != note["markdown"]
                or note_file.sha256 != note["note_sha256"]
                or note_file.role != "CANONICAL_NOTE"
            ):
                raise ValueError("Canonical note file differs from frozen source")
        if {path for path in by_path if path.startswith("notes/")} != expected_note_paths:
            raise ValueError("Unexpected canonical note files")
        idea_sources = receipt.get("source_manifest", {}).get("brief", {}).get("idea_sources", [])
        expected_idea_paths = set()
        for idea in idea_sources:
            path, content = idea_source_file(idea)
            expected_idea_paths.add(path)
            actual = by_path[path]
            if (
                actual.content != content
                or actual.sha256 != hashlib.sha256(content.encode("utf-8")).hexdigest()
                or actual.role != "IDEA_SOURCE"
            ):
                raise ValueError("Idea/quote file differs from frozen source")
        if {path for path in by_path if path.startswith("ideas/")} != expected_idea_paths:
            raise ValueError("Unexpected Idea source files")
        recorded = [
            {
                "path": item.path,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "role": item.role,
            }
            for item in sorted(files, key=lambda item: item.path)
            if item.path != "manifest.json"
        ]
        if receipt.get("files") != recorded:
            raise ValueError("Manifest does not match payload")
        sums = "".join(
            f"{item.sha256}  {item.path}\n"
            for item in sorted(files, key=lambda item: item.path)
            if item.path not in {"manifest.json", "SHA256SUMS"}
        )
        if by_path["SHA256SUMS"].content != sums:
            raise ValueError("Checksum manifest differs")
    except (ValueError, KeyError, TypeError) as exc:
        raise _error(
            "SERVER_PACKAGE_RENDER_INVALID",
            "Actual file manifest violates the data package contract",
        ) from exc
    return files


def options(
    db: Session,
    owner: uuid.UUID,
    project_id: uuid.UUID,
    limit: int = 20,
    brief_cursor: str | None = None,
    archive_cursor: str | None = None,
) -> ServerTaskPackageOptions:
    project = get_project(db, owner, project_id)
    rows, brief_next = briefs.list_briefs(db, owner, project_id, limit, brief_cursor)
    brief_options = []
    for row in rows:
        detail = briefs.detail_out(db, row)
        brief_options.append(
            ServerPackageBriefOption(
                id=row.id,
                revision=row.revision,
                idea=row.idea,
                sha256=row.sha256,
                status=detail.status,
                context_current=detail.context_current,
                eligible=detail.status == "ACCEPTED"
                and detail.context_current
                and briefs._intact(db, row)
                and bool(row.stop_rules),
            )
        )
    query = (
        select(ProjectArchiveVersion, ProjectArchiveBinding)
        .join(ProjectArchiveBinding, ProjectArchiveBinding.id == ProjectArchiveVersion.binding_id)
        .where(
            ProjectArchiveVersion.user_id == owner,
            ProjectArchiveBinding.user_id == owner,
            ProjectArchiveBinding.project_id == project_id,
        )
    )
    if archive_cursor:
        date, identity = decode_cursor(archive_cursor)
        query = query.where(
            or_(
                ProjectArchiveVersion.created_at < date,
                and_(ProjectArchiveVersion.created_at == date, ProjectArchiveVersion.id < identity),
            )
        )
    versions = db.execute(
        query.order_by(
            ProjectArchiveVersion.created_at.desc(), ProjectArchiveVersion.id.desc()
        ).limit(limit + 1)
    ).all()
    archive_next = (
        encode_cursor(versions[limit - 1][0].created_at, versions[limit - 1][0].id)
        if len(versions) > limit
        else None
    )
    return ServerTaskPackageOptions(
        owner_id=owner,
        project_id=project_id,
        project_name=project.name,
        briefs=brief_options,
        archive_versions=[
            ServerPackageArchiveOption(
                id=v.id,
                tag=v.tag,
                commit_sha=v.commit_sha,
                repository=b.github_owner + "/" + b.github_repository,
                remote_verified_at=v.remote_verified_at,
            )
            for v, b in versions[:limit]
        ],
        brief_page=PageMeta(limit=limit, next_cursor=brief_next),
        archive_page=PageMeta(limit=limit, next_cursor=archive_next),
        scope_note=SCOPE_NOTE,
    )


def _preview(
    db: Session, owner: uuid.UUID, project_id: uuid.UUID, selection: ServerTaskPackageSelection
) -> tuple[ServerTaskPackagePreviewOut, dict[str, Any], ServerPackageRenderedBundle]:
    manifest, markdown, gaps = _source(db, owner, project_id, selection)
    try:
        bundle = registry.server_task_package_renderer().render(
            brief_markdown=markdown,
            source_manifest=manifest,
            selection=selection.model_dump(mode="json"),
            gaps=tuple(gaps),
        )
    except ValueError as exc:
        raise _error("SERVER_PACKAGE_MATERIAL_INVALID", str(exc), 422) from exc
    files = _verify_bundle(bundle)
    receipt = json.loads(next(x.content for x in files if x.path == "manifest.json"))
    if (
        receipt.get("source_manifest") != manifest
        or receipt.get("selection") != selection.model_dump(mode="json")
        or receipt.get("gaps") != gaps
        or receipt.get("readiness") != ("INCOMPLETE" if gaps else "READY_FOR_SERVER_REVIEW")
    ):
        raise _error(
            "SERVER_PACKAGE_RENDER_INVALID", "Renderer changed approved source or selection"
        )
    source_sha = briefs.digest(manifest)
    preview_sha = briefs.digest(
        {
            "source_sha256": source_sha,
            "selection": selection.model_dump(mode="json"),
            "files": [x.model_dump() for x in files],
            "bundle_sha256": bundle.sha256,
            "readiness": "INCOMPLETE" if gaps else "READY_FOR_SERVER_REVIEW",
            "gaps": gaps,
        }
    )
    result = ServerTaskPackagePreviewOut(
        project_id=project_id,
        project_name=str(manifest["project"]["name"]),
        selection=selection,
        source_sha256=source_sha,
        preview_sha256=preview_sha,
        readiness="INCOMPLETE" if gaps else "READY_FOR_SERVER_REVIEW",
        gaps=gaps,
        files=files,
        bundle_sha256=bundle.sha256,
        bundle_size_bytes=bundle.size_bytes,
        scope_note=SCOPE_NOTE,
    )
    return result, manifest, bundle


def preview(
    db: Session, owner: uuid.UUID, project_id: uuid.UUID, selection: ServerTaskPackageSelection
) -> ServerTaskPackagePreviewOut:
    return _preview(db, owner, project_id, selection)[0]


def get_package(
    db: Session, owner: uuid.UUID, project_id: uuid.UUID, identity: uuid.UUID
) -> ServerTaskPackage:
    get_project(db, owner, project_id)
    row = db.scalar(
        select(ServerTaskPackage)
        .where(
            ServerTaskPackage.id == identity,
            ServerTaskPackage.user_id == owner,
            ServerTaskPackage.project_id == project_id,
        )
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise _error("NOT_FOUND", "Owned server package not found", 404)
    return row


def _children[
    ChildT: (
        ServerTaskPackageFile,
        ServerTaskPackageAsset,
        ServerTaskPackageExpectedArtifact,
        ServerTaskPackageTask,
    )
](db: Session, row: ServerTaskPackage, model: type[ChildT]) -> list[ChildT]:
    return list(
        db.scalars(
            select(model)
            .where(
                model.package_id == row.id,
                model.user_id == row.user_id,
                model.project_id == row.project_id,
            )
            .order_by(model.position)
        )
    )


def summary_out(row: ServerTaskPackage) -> ServerTaskPackageSummary:
    return ServerTaskPackageSummary.model_validate(
        {name: getattr(row, name) for name in ServerTaskPackageSummary.model_fields}
    )


def detail_out(db: Session, row: ServerTaskPackage) -> ServerTaskPackageOut:
    attempts = list(
        db.scalars(
            select(ServerTaskPackageSaveAttempt)
            .where(
                ServerTaskPackageSaveAttempt.package_id == row.id,
                ServerTaskPackageSaveAttempt.user_id == row.user_id,
            )
            .order_by(ServerTaskPackageSaveAttempt.attempt_number)
        )
    )

    def values(item: Any, names: Iterable[str]) -> dict[str, Any]:
        return {name: getattr(item, name) for name in names}

    return ServerTaskPackageOut(
        **summary_out(row).model_dump(),
        brief_id=row.brief_id,
        archive_version_id=row.archive_version_id,
        source_sha256=row.source_sha256,
        bundle_size_bytes=row.bundle_size_bytes,
        gaps=row.gaps,
        files=[
            values(x, ServerPackageFileOut.model_fields)
            for x in _children(db, row, ServerTaskPackageFile)
        ],
        assets=[
            values(x, ("kind", "label", "location", "version", "sha256", "license_note"))
            for x in _children(db, row, ServerTaskPackageAsset)
        ],
        expected_artifacts=[
            values(x, ("path", "description"))
            for x in _children(db, row, ServerTaskPackageExpectedArtifact)
        ],
        tasks=[
            values(x, ("task_id", "title", "description", "category", "priority"))
            for x in _children(db, row, ServerTaskPackageTask)
        ],
        save_attempts=[
            ServerPackageSaveAttemptOut.model_validate(
                values(x, ServerPackageSaveAttemptOut.model_fields)
            )
            for x in attempts
        ],
        scope_note=SCOPE_NOTE,
    )


def list_packages(
    db: Session, owner: uuid.UUID, project_id: uuid.UUID, limit: int = 20, cursor: str | None = None
) -> tuple[list[ServerTaskPackage], str | None]:
    get_project(db, owner, project_id)
    query = select(ServerTaskPackage).where(
        ServerTaskPackage.user_id == owner, ServerTaskPackage.project_id == project_id
    )
    if cursor:
        date, identity = decode_cursor(cursor)
        query = query.where(
            or_(
                ServerTaskPackage.created_at < date,
                and_(ServerTaskPackage.created_at == date, ServerTaskPackage.id < identity),
            )
        )
    rows = list(
        db.scalars(
            query.order_by(ServerTaskPackage.created_at.desc(), ServerTaskPackage.id.desc()).limit(
                limit + 1
            )
        )
    )
    return rows[:limit], encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id) if len(
        rows
    ) > limit else None


def _frozen_intact(db: Session, row: ServerTaskPackage) -> bool:
    selection = ServerTaskPackageSelection.model_validate(row.selection_snapshot)
    actual_assets = [
        {
            name: getattr(x, name)
            for name in ("kind", "label", "location", "version", "sha256", "license_note")
        }
        for x in _children(db, row, ServerTaskPackageAsset)
    ]
    actual_outputs = [
        {name: getattr(x, name) for name in ("path", "description")}
        for x in _children(db, row, ServerTaskPackageExpectedArtifact)
    ]
    actual_tasks = [
        {name: getattr(x, name) for name in ("title", "description", "category", "priority")}
        for x in _children(db, row, ServerTaskPackageTask)
    ]
    files = [
        ServerPackageFileOut(
            path=x.path, content=x.content, role=x.role, sha256=x.sha256, size_bytes=x.size_bytes
        )
        for x in _children(db, row, ServerTaskPackageFile)
    ]
    valid_files = all(
        hashlib.sha256(x.content.encode("utf-8")).hexdigest() == x.sha256
        and len(x.content.encode("utf-8")) == x.size_bytes
        for x in files
    )
    expected = briefs.digest(
        {
            "source_sha256": row.source_sha256,
            "selection": selection.model_dump(mode="json"),
            "files": [x.model_dump() for x in files],
            "bundle_sha256": row.bundle_sha256,
            "readiness": row.readiness,
            "gaps": row.gaps,
        }
    )
    return (
        valid_files
        and expected == row.preview_sha256
        and briefs.digest(row.source_snapshot) == row.source_sha256
        and actual_assets == [x.model_dump() for x in selection.assets]
        and actual_outputs == [x.model_dump() for x in selection.expected_artifacts]
        and actual_tasks == [x.model_dump() for x in selection.tasks]
    )


def _begin_attempt(
    db: Session, row: ServerTaskPackage, ack: bool = False
) -> ServerTaskPackageSaveAttempt:
    number = (
        db.scalar(
            select(func.max(ServerTaskPackageSaveAttempt.attempt_number)).where(
                ServerTaskPackageSaveAttempt.package_id == row.id
            )
        )
        or 0
    ) + 1
    attempt = ServerTaskPackageSaveAttempt(
        id=uuid.uuid4(),
        package_id=row.id,
        project_id=row.project_id,
        user_id=row.user_id,
        attempt_number=number,
        token=uuid.uuid4(),
        status="SAVING",
        owner_acknowledged_unknown=ack,
    )
    row.status = "SAVING"
    row.active_attempt_token = attempt.token
    row.error_code = None
    row.error_message = None
    db.add(attempt)
    return attempt


async def create_package(
    db: Session, owner: uuid.UUID, project_id: uuid.UUID, body: ServerTaskPackageCreateRequest
) -> ServerTaskPackage:
    if not body.approve_package:
        raise _error(
            "SERVER_PACKAGE_APPROVAL_REQUIRED", "Explicit package approval is required", 422
        )
    get_project(db, owner, project_id)
    existing = db.scalar(
        select(ServerTaskPackage).where(
            ServerTaskPackage.user_id == owner,
            ServerTaskPackage.project_id == project_id,
            ServerTaskPackage.idempotency_key == body.idempotency_key,
        )
    )
    if existing:
        if (
            existing.preview_sha256 != body.expected_preview_sha256
            or existing.selection_snapshot != body.selection.model_dump(mode="json")
        ):
            raise _error("IDEMPOTENCY_CONFLICT", "This key belongs to a different frozen package")
        return existing
    result, manifest, bundle = _preview(db, owner, project_id, body.selection)
    if result.preview_sha256 != body.expected_preview_sha256:
        raise _error(
            "SERVER_PACKAGE_PREVIEW_CHANGED", "Reload and approve the current exact preview"
        )
    row = ServerTaskPackage(
        id=uuid.uuid4(),
        user_id=owner,
        project_id=project_id,
        brief_id=body.selection.brief_id,
        archive_version_id=body.selection.archive_version_id,
        archive_binding_id=uuid.UUID(manifest["archive"]["binding"]["id"])
        if manifest["archive"]
        else None,
        label=body.selection.label,
        idempotency_key=body.idempotency_key,
        status="SAVING",
        readiness=result.readiness,
        source_sha256=result.source_sha256,
        preview_sha256=result.preview_sha256,
        bundle_sha256=result.bundle_sha256,
        bundle_size_bytes=result.bundle_size_bytes,
        source_snapshot=manifest,
        selection_snapshot=body.selection.model_dump(mode="json"),
        gaps=result.gaps,
    )
    db.add(row)
    try:
        db.flush()
        for model, items in (
            (ServerTaskPackageFile, result.files),
            (ServerTaskPackageAsset, body.selection.assets),
            (ServerTaskPackageExpectedArtifact, body.selection.expected_artifacts),
            (ServerTaskPackageTask, body.selection.tasks),
        ):
            db.add_all(
                model(
                    package_id=row.id,
                    project_id=project_id,
                    user_id=owner,
                    position=i,
                    **item.model_dump(),
                )
                for i, item in enumerate(items)
            )
        attempt = _begin_attempt(db, row)
        db.commit()
    except IntegrityError:
        db.rollback()
        winner = db.scalar(
            select(ServerTaskPackage).where(
                ServerTaskPackage.user_id == owner,
                ServerTaskPackage.project_id == project_id,
                ServerTaskPackage.idempotency_key == body.idempotency_key,
            )
        )
        if (
            winner
            and winner.preview_sha256 == body.expected_preview_sha256
            and winner.selection_snapshot == body.selection.model_dump(mode="json")
        ):
            return winner
        raise _error(
            "SERVER_PACKAGE_CREATE_CONFLICT", "Another package was committed; reload the stable key"
        ) from None
    return await _save(db, row, attempt, bundle)


async def _save(
    db: Session,
    row: ServerTaskPackage,
    attempt: ServerTaskPackageSaveAttempt,
    bundle: ServerPackageRenderedBundle,
) -> ServerTaskPackage:
    identity, owner, project_id, token, attempt_id = (
        row.id,
        row.user_id,
        row.project_id,
        attempt.token,
        attempt.id,
    )
    provider = None
    save_started = False
    content, sha, size = bundle.content, bundle.sha256, bundle.size_bytes
    db.rollback()
    stored = None
    verified = False
    error = None

    async def chunks() -> AsyncIterator[bytes]:
        yield content

    try:
        provider = registry.storage_provider()
        save_started = True
        stored = await provider.save(chunks(), mime_type="application/zip", max_bytes=MAX_BYTES)
        if (
            stored.sha256 != sha
            or stored.size_bytes != size
            or stored.mime_type != "application/zip"
            or not stored.key
            or len(stored.key) > 320
        ):
            raise _error("STORAGE_RECEIPT_INVALID", "Storage receipt differs from the approved ZIP")
        reader = await provider.open(stored.key)
        actual = bytearray()
        try:
            if reader.size_bytes != size:
                raise _error("STORAGE_OBJECT_CHANGED", "Stored size differs from approved ZIP")
            async for chunk in reader.iter_bytes():
                actual.extend(chunk)
                if len(actual) > MAX_BYTES:
                    raise _error("STORAGE_OBJECT_CHANGED", "Stored ZIP exceeds package limits")
        finally:
            await reader.close()
        if bytes(actual) != content or hashlib.sha256(actual).hexdigest() != sha:
            raise _error(
                "STORAGE_OBJECT_CHANGED", "Actual stored ZIP bytes differ from approved preview"
            )
        verified = True
    except Exception as exc:
        error = exc
    _fresh(db)
    from app.models import User

    db.scalar(select(User).where(User.id == owner).with_for_update())
    current = db.scalar(
        select(ServerTaskPackage)
        .where(
            ServerTaskPackage.id == identity,
            ServerTaskPackage.user_id == owner,
            ServerTaskPackage.project_id == project_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current is None:
        raise _error("NOT_FOUND", "Owned package disappeared", 404)
    saved_attempt = db.get(ServerTaskPackageSaveAttempt, attempt_id)
    if saved_attempt is None:
        raise _error("SERVER_PACKAGE_ATTEMPT_MISSING", "Save attempt record is unavailable")
    saved_attempt.finished_at = datetime.now(UTC)
    if stored:
        assert provider is not None
        saved_attempt.storage_provider = (
            provider.provider_key if len(provider.provider_key) <= 64 else None
        )
        saved_attempt.object_key = (
            stored.key if isinstance(stored.key, str) and len(stored.key) <= 320 else None
        )
        saved_attempt.observed_sha256 = (
            stored.sha256
            if isinstance(stored.sha256, str) and re.fullmatch(r"[0-9a-f]{64}", stored.sha256)
            else None
        )
        saved_attempt.observed_size_bytes = (
            stored.size_bytes
            if isinstance(stored.size_bytes, int) and -(2**63) <= stored.size_bytes < 2**63
            else None
        )
        saved_attempt.observed_mime_type = (
            stored.mime_type
            if isinstance(stored.mime_type, str) and len(stored.mime_type) <= 120
            else None
        )
    if current.active_attempt_token != token or current.status != "SAVING":
        if verified and stored and provider:
            fact = db.scalar(select(Attachment).where(Attachment.object_key == stored.key))
            if fact is None:
                fact = Attachment(
                    id=uuid.uuid4(),
                    user_id=owner,
                    storage_provider=provider.provider_key,
                    object_key=stored.key,
                    original_filename=f"server-task-{identity}.zip",
                    mime_type="application/zip",
                    sha256=sha,
                    size_bytes=size,
                )
                db.add(fact)
                db.flush()
            if (
                fact.user_id == owner
                and fact.sha256 == sha
                and fact.size_bytes == size
                and fact.storage_provider == provider.provider_key
                and fact.mime_type == "application/zip"
                and fact.deleted_at is None
            ):
                saved_attempt.attachment_id = fact.id
        saved_attempt.status = "LATE"
        saved_attempt.error_code = "SAVE_CALLBACK_FENCED"
        db.commit()
        return current
    attachment = None
    if verified and stored:
        assert provider is not None
        attachment = db.scalar(select(Attachment).where(Attachment.object_key == stored.key))
        if attachment and (
            attachment.user_id != owner
            or attachment.sha256 != sha
            or attachment.size_bytes != size
            or attachment.storage_provider != provider.provider_key
            or attachment.mime_type != "application/zip"
            or attachment.deleted_at is not None
        ):
            error = _error(
                "STORAGE_OBJECT_CONFLICT", "Stored key is already registered with different facts"
            )
            verified = False
        if verified and attachment is None:
            attachment = Attachment(
                id=uuid.uuid4(),
                user_id=owner,
                storage_provider=provider.provider_key,
                object_key=stored.key,
                original_filename=f"server-task-{identity}.zip",
                mime_type="application/zip",
                sha256=sha,
                size_bytes=size,
            )
            db.add(attachment)
            db.flush()
        if verified:
            assert attachment is not None
            current.attachment_id = attachment.id
            saved_attempt.attachment_id = attachment.id
    drift = False
    if verified:
        try:
            manifest, _, _ = _source(
                db,
                owner,
                project_id,
                ServerTaskPackageSelection.model_validate(current.selection_snapshot),
                lock=True,
            )
            drift = briefs.digest(manifest) != current.source_sha256 or not _frozen_intact(
                db, current
            )
        except (DomainError, ValueError, TypeError):
            drift = True
    if error:
        saved_attempt.status = (
            "FAILED" if not save_started else "UNKNOWN" if stored is None else "QUARANTINED"
        )
        saved_attempt.error_code = getattr(error, "code", "STORAGE_SAVE_OUTCOME_UNKNOWN")
        current.status = "FAILED" if not save_started else "NEEDS_ATTENTION"
        current.error_code = saved_attempt.error_code
        current.error_message = "保存结果需核查；不会自动再次保存。"
    elif drift:
        saved_attempt.status = "QUARANTINED"
        saved_attempt.error_code = "SERVER_PACKAGE_SOURCE_CHANGED"
        current.status = "NEEDS_ATTENTION"
        current.error_code = saved_attempt.error_code
        current.error_message = "保存期间任务书、审核或代码来源变化；保留附件事实待核查。"
    else:
        saved_attempt.status = "SAVED"
        current.status = "READY"
        current.completed_at = datetime.now(UTC)
        for planned in _children(db, current, ServerTaskPackageTask):
            if planned.task_id is None:
                entity = ResearchEntity(user_id=owner, kind="task")
                db.add(entity)
                db.flush()
                db.add(
                    Task(
                        id=entity.id,
                        user_id=owner,
                        project_id=project_id,
                        title=planned.title,
                        description=planned.description,
                        category=planned.category,
                        priority=planned.priority,
                        status="todo",
                    )
                )
                db.flush()
                planned.task_id = entity.id
    current.active_attempt_token = None
    try:
        db.commit()
    except Exception:
        db.rollback()
        # A lost commit acknowledgement is queried, never replayed or deleted.
        current = get_package(db, owner, project_id, identity)
        if current.status == "READY":
            return current
        if current.active_attempt_token == token and current.status == "SAVING":
            observed = db.get(ServerTaskPackageSaveAttempt, attempt_id)
            if observed is not None:
                observed.status = "UNKNOWN"
                observed.error_code = "SERVER_PACKAGE_COMMIT_UNKNOWN"
                observed.finished_at = datetime.now(UTC)
                if stored is not None and provider is not None:
                    observed.storage_provider = provider.provider_key
                    observed.object_key = stored.key
                    observed.observed_sha256 = stored.sha256
                    observed.observed_size_bytes = stored.size_bytes
                    observed.observed_mime_type = stored.mime_type
                    if verified:
                        fact = db.scalar(
                            select(Attachment).where(Attachment.object_key == stored.key)
                        )
                        if fact is None:
                            fact = Attachment(
                                id=uuid.uuid4(),
                                user_id=owner,
                                storage_provider=provider.provider_key,
                                object_key=stored.key,
                                original_filename=f"server-task-{identity}.zip",
                                mime_type="application/zip",
                                sha256=sha,
                                size_bytes=size,
                            )
                            db.add(fact)
                            db.flush()
                        if (
                            fact.user_id == owner
                            and fact.sha256 == sha
                            and fact.size_bytes == size
                            and fact.mime_type == "application/zip"
                            and fact.storage_provider == provider.provider_key
                            and fact.deleted_at is None
                        ):
                            current.attachment_id = fact.id
                            observed.attachment_id = fact.id
                current.status = "NEEDS_ATTENTION"
                current.active_attempt_token = None
                current.error_code = "SERVER_PACKAGE_COMMIT_UNKNOWN"
                current.error_message = (
                    "存储字节已核查，但提交结果需明确核查；不会重复保存或创建任务。"
                )
                db.commit()
                return current
        raise _error(
            "SERVER_PACKAGE_COMMIT_UNKNOWN",
            "Reload this package; saving will not be replayed automatically",
        ) from None
    db.refresh(current)
    return current


async def retry_save(
    db: Session,
    owner: uuid.UUID,
    project_id: uuid.UUID,
    identity: uuid.UUID,
    body: ServerTaskPackageRetryRequest,
) -> ServerTaskPackage:
    row = db.scalar(
        select(ServerTaskPackage)
        .where(
            ServerTaskPackage.id == identity,
            ServerTaskPackage.user_id == owner,
            ServerTaskPackage.project_id == project_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise _error("NOT_FOUND", "Owned server package not found", 404)
    if row.preview_sha256 != body.expected_preview_sha256:
        raise _error(
            "SERVER_PACKAGE_PREVIEW_CHANGED", "Retry must reference the exact frozen package"
        )
    if row.status == "READY":
        return row
    previous = None
    if row.status == "SAVING":
        previous = db.scalar(
            select(ServerTaskPackageSaveAttempt)
            .where(
                ServerTaskPackageSaveAttempt.package_id == row.id,
                ServerTaskPackageSaveAttempt.user_id == owner,
                ServerTaskPackageSaveAttempt.token == row.active_attempt_token,
            )
            .with_for_update()
        )
        if previous is None:
            raise _error("SERVER_PACKAGE_ATTEMPT_MISSING", "The active save receipt is missing")
        started = (
            previous.started_at.replace(tzinfo=UTC)
            if previous.started_at.tzinfo is None
            else previous.started_at
        )
        if (datetime.now(UTC) - started).total_seconds() < 300:
            raise _error(
                "SERVER_PACKAGE_SAVE_ACTIVE",
                "The save may still be active; unknown-save recovery is available after five minutes",
            )
        if not body.acknowledge_unknown_save:
            raise _error(
                "SERVER_PACKAGE_SAVE_ACK_REQUIRED",
                "Acknowledge that the old save may still finish before fencing its token",
                422,
            )
    if row.status == "NEEDS_ATTENTION" and not body.acknowledge_unknown_save:
        raise _error(
            "SERVER_PACKAGE_SAVE_ACK_REQUIRED",
            "Explicitly acknowledge the uncertain previous save before retry",
            422,
        )
    manifest, _, _ = _source(
        db, owner, project_id, ServerTaskPackageSelection.model_validate(row.selection_snapshot)
    )
    if briefs.digest(manifest) != row.source_sha256 or not _frozen_intact(db, row):
        raise _error(
            "SERVER_PACKAGE_SOURCE_CHANGED", "Source changed; prepare a newly reviewed package"
        )
    from app.domain.server_packages import ServerPackageRenderedFile

    files = tuple(
        ServerPackageRenderedFile(
            path=x.path, content=x.content, role=x.role, sha256=x.sha256, size_bytes=x.size_bytes
        )
        for x in _children(db, row, ServerTaskPackageFile)
    )
    try:
        bundle = registry.server_task_package_renderer().pack(files=files)
    except ValueError as exc:
        raise _error(
            "SERVER_PACKAGE_FROZEN_CONTENT_INVALID", "Frozen files no longer match approved package"
        ) from exc
    _verify_bundle(bundle)
    if bundle.sha256 != row.bundle_sha256 or bundle.size_bytes != row.bundle_size_bytes:
        raise _error(
            "SERVER_PACKAGE_FROZEN_CONTENT_INVALID",
            "Frozen files no longer reproduce the approved ZIP",
        )
    if previous is not None:
        previous.status = "UNKNOWN"
        previous.error_code = "OWNER_FENCED_UNKNOWN_SAVE"
        previous.finished_at = datetime.now(UTC)
    attempt = _begin_attempt(db, row, body.acknowledge_unknown_save)
    db.commit()
    return await _save(db, row, attempt, bundle)


def download_attachment(
    db: Session, owner: uuid.UUID, project_id: uuid.UUID, identity: uuid.UUID
) -> Attachment:
    row = get_package(db, owner, project_id, identity)
    attachment = (
        db.scalar(
            select(Attachment).where(
                Attachment.id == row.attachment_id,
                Attachment.user_id == owner,
                Attachment.deleted_at.is_(None),
            )
        )
        if row.attachment_id
        else None
    )
    if (
        attachment is None
        or attachment.sha256 != row.bundle_sha256
        or attachment.size_bytes != row.bundle_size_bytes
        or attachment.mime_type != "application/zip"
    ):
        raise _error(
            "SERVER_PACKAGE_DOWNLOAD_UNAVAILABLE", "No verified stored ZIP is available", 404
        )
    return attachment
