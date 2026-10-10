"""Readonly baseline bytes and closed dataset splits; no repository execution."""

import asyncio
import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

import app.domain.baselines as baseline_domain
from app.core.config import get_settings
from app.domain.baselines import (
    BaselineAssetObservation,
    BaselineAssetStatus,
    BaselineProbeAsset,
    BaselineProbeRequest,
    BaselineProbeResult,
    DatasetSplitManifestV1,
)
from app.domain.project_sources import ProjectSourceFile, ProjectSourceScope
from app.errors import DomainError
from app.providers.project_sources import (
    MARKER,
    LocalProjectSourceWorkspaceProvider,
    _parts,
    _path,
    _signature,
)

CHECKER_VERSION = "baseline-material-v1"
# Freeze installed source identity at import, alongside the loaded algorithm;
# later edits on disk must not relabel an already-running checker instance.
CHECKER_SHA256 = hashlib.sha256(
    Path(__file__).read_bytes() + Path(baseline_domain.__file__).read_bytes()
).hexdigest()
MAX_CONTENT = 4 * 1024 * 1024
MAX_ASSETS = 10000
ROLES = {"CODE", "CONFIG", "ENVIRONMENT_LOCK", "EVALUATOR", "WEIGHTS", "DATA", "SPLIT_MANIFEST"}


@dataclass(frozen=True)
class _ScopeFence:
    workspace: LocalProjectSourceWorkspaceProvider
    scope: ProjectSourceScope
    first: ProjectSourceFile
    target: Path
    marker_bytes: bytes
    marker_stat: tuple[int, int, int, int, int]
    binding_stat: tuple[int, int, int, int, int]
    root_id: tuple[int, int]
    git_id: tuple[int, int]
    files: frozenset[ProjectSourceFile]

    @classmethod
    def create(
        cls, workspace: LocalProjectSourceWorkspaceProvider, asset: BaselineProbeAsset
    ) -> "_ScopeFence":
        # This validates all frozen identities and recomputes the complete
        # approved marker. It does not inspect or hash asset bytes.
        workspace._allowed(asset.source_scope, asset.source_file)
        target = workspace.root / asset.source_scope.relative_path
        marker = target / MARKER
        content = workspace._read(marker)
        files = workspace._marker_files
        if files is None or content != workspace._marker(asset.source_scope, tuple(files)):
            raise DomainError("PROJECT_SOURCE_WORKSPACE_CONFLICT", "Source marker changed", 409)
        root, git = workspace.root.stat(), (workspace.root / ".git").stat()
        return cls(
            workspace,
            asset.source_scope,
            asset.source_file,
            target,
            content,
            _signature(marker.stat()),
            _signature((workspace.root / ".git/researchos/binding.json").stat()),
            (root.st_dev, root.st_ino),
            (git.st_dev, git.st_ino),
            frozenset(files),
        )

    def path(self, asset: BaselineProbeAsset) -> Path:
        if asset.source_scope != self.scope or asset.source_file not in self.files:
            raise DomainError("PROJECT_SOURCE_WORKSPACE_CONFLICT", "Source scope changed", 409)
        for path in (
            self.workspace.root,
            self.workspace.root / ".git",
            self.target,
            self.target / MARKER,
            self.workspace.root / ".git/researchos/binding.json",
        ):
            _path(path)
        root, git = self.workspace.root.stat(), (self.workspace.root / ".git").stat()
        if (
            (root.st_dev, root.st_ino) != self.root_id
            or (git.st_dev, git.st_ino) != self.git_id
            or _signature((self.target / MARKER).stat()) != self.marker_stat
            or _signature((self.workspace.root / ".git/researchos/binding.json").stat())
            != self.binding_stat
        ):
            raise DomainError(
                "PROJECT_SOURCE_WORKSPACE_CONFLICT", "Source authority identity changed", 409
            )
        path = self.target.joinpath(*_parts(asset.source_file.path))
        _path(path)
        return path

    def finish(self) -> None:
        self.workspace._allowed(self.scope, self.first)
        if self.workspace._read(self.target / MARKER) != self.marker_bytes:
            raise DomainError(
                "PROJECT_SOURCE_WORKSPACE_CONFLICT", "Source authority marker changed", 409
            )


@dataclass(frozen=True)
class _MeasuredFileFence:
    scope: _ScopeFence
    asset: BaselineProbeAsset
    path: Path
    signature: tuple[int, int, int, int, int]
    ctime_ns: int

    def final_issue(self) -> tuple[BaselineAssetStatus, str] | None:
        """Recheck identity after all reads, without a second byte/hash pass."""
        try:
            path = self.scope.path(self.asset)
            if path != self.path:
                return "UNSAFE", "SOURCE_PATH_CHANGED_AFTER_READ"
            info = path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                return "UNSAFE", "SOURCE_PATH_UNSAFE_AFTER_READ"
            if _signature(info) != self.signature or info.st_ctime_ns != self.ctime_ns:
                return "CHANGED", "SOURCE_FILE_CHANGED_AFTER_READ"
        except FileNotFoundError:
            return "CHANGED", "SOURCE_FILE_MISSING_AFTER_READ"
        except DomainError:
            return "UNSAFE", "SOURCE_PATH_UNSAFE_AFTER_READ"
        except OSError:
            return "UNAVAILABLE", "SOURCE_FINAL_STAT_UNAVAILABLE"
        return None


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _json(content: bytes) -> object:
    def invalid_constant(value: str) -> object:
        raise ValueError("nonfinite JSON value")

    return json.loads(content, object_pairs_hook=_unique, parse_constant=invalid_constant)


def validate_dataset_split_manifest(
    content: bytes,
    dataset_version_id: uuid.UUID,
    data_assets: tuple[BaselineProbeAsset, ...],
    observations: tuple[BaselineAssetObservation, ...],
) -> DatasetSplitManifestV1:
    """Exact DATA closure and independent sample/group splits, never a user flag."""
    if len(content) > MAX_CONTENT:
        raise ValueError("SPLIT_MANIFEST_TOO_LARGE")
    try:
        raw = _json(content)  # Reject duplicate keys before typed JSON decoding.
        if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int:
            raise ValueError("Missing explicit integer schema version")
        manifest = DatasetSplitManifestV1.model_validate_json(content, strict=True)
    except (ValueError, ValidationError, RecursionError) as error:
        raise ValueError("SPLIT_MANIFEST_INVALID") from error
    if manifest.dataset_version_id != dataset_version_id:
        raise ValueError("SPLIT_DATASET_MISMATCH")
    if {split.name for split in manifest.splits} != {"TRAIN", "VALIDATION", "TEST"}:
        raise ValueError("SPLIT_NAMES_INVALID")
    matching = tuple(
        asset for asset in data_assets if asset.dataset_version_id == dataset_version_id
    )
    actual = {observation.asset_id: observation for observation in observations}
    expected = {asset.source_file.path: asset for asset in matching}
    if not matching or len(expected) != len(matching):
        raise ValueError("SPLIT_DATA_CLOSURE_AMBIGUOUS")
    seen_paths: set[str] = set()
    samples: set[str] = set()
    groups: dict[str, str] = {}
    for split in manifest.splits:
        for sample in split.samples:
            try:
                _parts(sample.path)
            except DomainError as error:
                raise ValueError("SPLIT_PATH_UNSAFE") from error
            if not sample.sample_id.strip() or not sample.group_id.strip():
                raise ValueError("SPLIT_ID_INVALID")
            if sample.sample_id in samples or sample.path in seen_paths:
                raise ValueError("SPLIT_DUPLICATE_SAMPLE")
            if sample.group_id in groups and groups[sample.group_id] != split.name:
                raise ValueError("SPLIT_GROUP_LEAKAGE")
            asset = expected.get(sample.path)
            observation = actual.get(asset.asset_id) if asset else None
            if (
                asset is None
                or observation is None
                or observation.status != "VERIFIED"
                or (sample.sha256, sample.size_bytes)
                != (asset.source_file.sha256, asset.source_file.size_bytes)
                or (sample.sha256, sample.size_bytes)
                != (observation.actual_sha256, observation.actual_size_bytes)
            ):
                raise ValueError("SPLIT_SAMPLE_NOT_MEASURED")
            samples.add(sample.sample_id)
            seen_paths.add(sample.path)
            groups[sample.group_id] = split.name
    if seen_paths != set(expected):
        raise ValueError("SPLIT_DATA_CLOSURE_INCOMPLETE")
    return manifest


class LocalBaselineAssetProbeProvider:
    """Resolver accepts frozen authority, never a browser-supplied disk path.

    Owner grant/job revocation is fenced by the service before and after this
    provider. Filesystem observations alone cannot prove a current DB grant.
    """

    def __init__(
        self,
        resolver: Callable[[ProjectSourceScope], LocalProjectSourceWorkspaceProvider],
        *,
        max_bytes: int | None = None,
        max_files: int | None = None,
    ) -> None:
        self._resolver = resolver
        settings = get_settings()
        self.max_bytes = settings.repository_asset_max_bytes if max_bytes is None else max_bytes
        self.max_files = settings.repository_asset_max_files if max_files is None else max_files
        if (
            type(self.max_bytes) is not int
            or type(self.max_files) is not int
            or self.max_bytes <= 0
            or not 0 < self.max_files <= MAX_ASSETS
        ):
            raise ValueError("Invalid baseline probe resource budget")

    async def probe(self, request: BaselineProbeRequest) -> BaselineProbeResult:
        return await asyncio.to_thread(self._probe, request)

    def _read(
        self,
        asset: BaselineProbeAsset,
        *,
        fence: _ScopeFence,
        remaining_bytes: int,
        capture: bool,
        file_fences: dict[tuple[ProjectSourceScope, ProjectSourceFile], _MeasuredFileFence],
    ) -> tuple[BaselineAssetObservation, bytes | None]:
        now = datetime.now(UTC)
        digest, size, content = hashlib.sha256(), 0, bytearray()
        actual_sha: str | None = None
        actual_size: int | None = None
        try:
            workspace = fence.workspace
            path = fence.path(asset)
            _path(path)
            # lstat prevents a link installed between the ancestry check and
            # the file identity snapshot from being followed before reading.
            before_path = path.lstat()
            actual_size = before_path.st_size
            if not stat.S_ISREG(before_path.st_mode) or before_path.st_size > workspace.max_bytes:
                return BaselineAssetObservation(
                    asset.asset_id,
                    "UNSAFE",
                    None,
                    actual_size,
                    "SOURCE_FILE_UNSAFE_OR_TOO_LARGE",
                    now,
                ), None
            if before_path.st_size > remaining_bytes:
                return BaselineAssetObservation(
                    asset.asset_id,
                    "UNAVAILABLE",
                    None,
                    actual_size,
                    "PROBE_BYTE_BUDGET_EXCEEDED",
                    now,
                ), None
            with path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                if _signature(before) != _signature(before_path):
                    raise DomainError("PROJECT_SOURCE_FILE_CHANGED", "Source identity changed", 409)
                while chunk := stream.read(min(65536, remaining_bytes - size + 1)):
                    size += len(chunk)
                    if size > min(workspace.max_bytes, remaining_bytes):
                        raise DomainError("PROJECT_SOURCE_FILE_CHANGED", "Source size changed", 409)
                    digest.update(chunk)
                    # All assets get a bounded prefix for LFS pointer checks;
                    # config and manifest bytes never exceed the 4 MiB limit.
                    limit = MAX_CONTENT if capture else 4096
                    if len(content) < limit:
                        content.extend(chunk[: limit - len(content)])
                after = os.fstat(stream.fileno())
            actual_sha, actual_size = digest.hexdigest(), size
            _path(path)
            final_path_info = path.lstat()
            if (
                _signature(before) != _signature(after)
                or _signature(after) != _signature(final_path_info)
                or fence.path(asset) != path
                or (actual_sha, size) != (asset.source_file.sha256, asset.source_file.size_bytes)
            ):
                return BaselineAssetObservation(
                    asset.asset_id, "CHANGED", actual_sha, size, "SOURCE_FILE_CHANGED", now
                ), None
            file_fences[(asset.source_scope, asset.source_file)] = _MeasuredFileFence(
                # Keep one stat API for ctime: Windows fstat and lstat can
                # expose different ctime semantics for the same stable file.
                fence,
                asset,
                path,
                _signature(final_path_info),
                final_path_info.st_ctime_ns,
            )
            if content.startswith(b"version https://git-lfs.github.com/spec/v1"):
                return BaselineAssetObservation(
                    asset.asset_id,
                    "UNAVAILABLE",
                    actual_sha,
                    size,
                    "GIT_LFS_OBJECT_NOT_MATERIALIZED",
                    now,
                ), None
            if capture and size > MAX_CONTENT:
                return BaselineAssetObservation(
                    asset.asset_id, "UNAVAILABLE", actual_sha, size, "BOUNDED_CONTENT_LIMIT", now
                ), None
            return BaselineAssetObservation(
                asset.asset_id, "VERIFIED", actual_sha, size, None, now
            ), bytes(content)
        except FileNotFoundError:
            return BaselineAssetObservation(
                asset.asset_id, "MISSING", actual_sha, actual_size, "SOURCE_FILE_MISSING", now
            ), None
        except DomainError as error:
            status: BaselineAssetStatus = (
                "CHANGED" if error.code == "PROJECT_SOURCE_FILE_CHANGED" else "UNSAFE"
            )
            return BaselineAssetObservation(
                asset.asset_id, status, actual_sha, actual_size, error.code, now
            ), None
        except OSError:
            return BaselineAssetObservation(
                asset.asset_id,
                "UNAVAILABLE",
                actual_sha,
                actual_size,
                "SOURCE_READ_UNAVAILABLE",
                now,
            ), None

    def _probe(self, request: BaselineProbeRequest) -> BaselineProbeResult:
        checker_sha = CHECKER_SHA256
        valid_request = (
            bool(request.assets)
            and len(request.assets) <= MAX_ASSETS
            and re.fullmatch(r"[a-f0-9]{64}", request.version_sha256) is not None
            and len({asset.asset_id for asset in request.assets}) == len(request.assets)
            and len(set(request.dataset_version_ids)) == len(request.dataset_version_ids)
            and all(
                asset.role in ROLES
                and asset.source_scope.owner_id == request.owner_id
                and asset.source_scope.project_id == request.project_id
                and (
                    asset.role not in {"DATA", "SPLIT_MANIFEST"}
                    or asset.dataset_version_id in request.dataset_version_ids
                )
                for asset in request.assets
            )
        )
        if not valid_request:
            return BaselineProbeResult(
                checker_sha256=checker_sha,
                checker_version=CHECKER_VERSION,
                observations=(),
                gaps=("BASELINE_PROBE_SCOPE_INVALID",),
                split_valid=False,
            )
        unique_files = {(asset.source_scope, asset.source_file) for asset in request.assets}
        if (
            len(unique_files) > self.max_files
            or sum(file.size_bytes for _, file in unique_files) > self.max_bytes
        ):
            return BaselineProbeResult(
                CHECKER_VERSION,
                checker_sha,
                (),
                ("BASELINE_PROBE_RESOURCE_BUDGET_EXCEEDED",),
                False,
            )
        observations: list[BaselineAssetObservation] = []
        contents: dict[uuid.UUID, bytes] = {}
        gaps: list[str] = []
        measured: dict[
            tuple[ProjectSourceScope, ProjectSourceFile],
            tuple[BaselineAssetObservation, bytes | None],
        ] = {}
        measured_bytes = 0
        file_fences: dict[tuple[ProjectSourceScope, ProjectSourceFile], _MeasuredFileFence] = {}
        fences: dict[ProjectSourceScope, _ScopeFence | BaselineAssetObservation] = {}
        capture_files = {
            (entry.source_scope, entry.source_file)
            for entry in request.assets
            if entry.role in {"CONFIG", "ENVIRONMENT_LOCK", "SPLIT_MANIFEST"}
            or entry.source_file.path.endswith(".index.json")
        }
        for asset in request.assets:
            key = asset.source_scope, asset.source_file
            if key not in measured:
                if asset.source_scope not in fences:
                    try:
                        fences[asset.source_scope] = _ScopeFence.create(
                            self._resolver(asset.source_scope), asset
                        )
                    except FileNotFoundError:
                        fences[asset.source_scope] = BaselineAssetObservation(
                            asset.asset_id,
                            "MISSING",
                            None,
                            None,
                            "SOURCE_SCOPE_MISSING",
                            datetime.now(UTC),
                        )
                    except DomainError as error:
                        fences[asset.source_scope] = BaselineAssetObservation(
                            asset.asset_id, "UNSAFE", None, None, error.code, datetime.now(UTC)
                        )
                    except OSError:
                        fences[asset.source_scope] = BaselineAssetObservation(
                            asset.asset_id,
                            "UNAVAILABLE",
                            None,
                            None,
                            "SOURCE_SCOPE_UNAVAILABLE",
                            datetime.now(UTC),
                        )
                fence = fences[asset.source_scope]
                measured[key] = (
                    self._read(
                        asset,
                        fence=fence,
                        remaining_bytes=max(0, self.max_bytes - measured_bytes),
                        capture=key in capture_files,
                        file_fences=file_fences,
                    )
                    if isinstance(fence, _ScopeFence)
                    else (replace(fence, asset_id=asset.asset_id), None)
                )
                measured_bytes += measured[key][0].actual_size_bytes or 0
            original, content = measured[key]
            observation = BaselineAssetObservation(
                asset.asset_id,
                original.status,
                original.actual_sha256,
                original.actual_size_bytes,
                original.issue,
                original.checked_at,
            )
            observations.append(observation)
            if content is not None:
                contents[asset.asset_id] = content
            if observation.status != "VERIFIED":
                gaps.append(f"ASSET_{asset.asset_id}_{observation.issue}")
            if asset.source_file.path.endswith(".gitmodules"):
                gaps.append(f"ASSET_{asset.asset_id}_SUBMODULE_CONTENT_UNVERIFIED")
            if content is not None and asset.role in {"CONFIG", "ENVIRONMENT_LOCK"}:
                if re.search(
                    rb"(?:https?://|git\+|file://|[A-Za-z]:[\\/]|(?:^|[\s:=])/(?:home|mnt|opt|data)/)",
                    content,
                ):
                    gaps.append(f"ASSET_{asset.asset_id}_EXTERNAL_DEPENDENCIES_UNVERIFIED")
            if (
                content is not None
                and asset.role == "WEIGHTS"
                and asset.source_file.path.endswith(".index.json")
            ):
                try:
                    index = _json(content)
                    shards = index.get("weight_map") if isinstance(index, dict) else None
                    if (
                        not isinstance(shards, dict)
                        or not shards
                        or any(not isinstance(value, str) for value in shards.values())
                    ):
                        raise ValueError("invalid shards")
                    weights = {
                        entry.source_file.path
                        for entry in request.assets
                        if entry.role == "WEIGHTS" and entry.source_scope == asset.source_scope
                    }
                    parent = PurePosixPath(asset.source_file.path).parent
                    for value in set(shards.values()):
                        if not isinstance(value, str):
                            raise ValueError("invalid shard")
                        _parts(value)
                        if (
                            str(parent / value) not in weights
                            or str(parent / value) == asset.source_file.path
                        ):
                            raise ValueError("missing shard")
                except (ValueError, DomainError, UnicodeError, RecursionError):
                    gaps.append(f"ASSET_{asset.asset_id}_WEIGHT_SHARDS_UNVERIFIED")
            if asset.role == "WEIGHTS" and re.search(r"-\d{5}-of-\d{5}\.", asset.source_file.path):
                index_parent = PurePosixPath(asset.source_file.path).parent
                if not any(
                    entry.role == "WEIGHTS"
                    and entry.source_scope == asset.source_scope
                    and entry.source_file.path.endswith(".index.json")
                    and PurePosixPath(entry.source_file.path).parent == index_parent
                    for entry in request.assets
                ):
                    gaps.append(f"ASSET_{asset.asset_id}_WEIGHT_SHARD_INDEX_MISSING")
        for scope, fence in fences.items():
            if not isinstance(fence, _ScopeFence):
                continue
            try:
                fence.finish()
            except (DomainError, OSError):
                affected = {
                    asset.asset_id for asset in request.assets if asset.source_scope == scope
                }
                observations = [
                    replace(row, status="UNSAFE", issue="SOURCE_SCOPE_CHANGED_DURING_PROBE")
                    if row.asset_id in affected
                    else row
                    for row in observations
                ]
                gaps.append(f"SOURCE_{scope.plan_id}_SCOPE_CHANGED_DURING_PROBE")
        split_valid = bool(request.dataset_version_ids)
        for dataset in request.dataset_version_ids:
            manifests = [
                asset
                for asset in request.assets
                if asset.role == "SPLIT_MANIFEST" and asset.dataset_version_id == dataset
            ]
            if len(manifests) != 1 or manifests[0].asset_id not in contents:
                split_valid = False
                gaps.append(f"DATASET_{dataset}_SPLIT_MANIFEST_NOT_MEASURED")
                continue
            try:
                validate_dataset_split_manifest(
                    contents[manifests[0].asset_id],
                    dataset,
                    tuple(asset for asset in request.assets if asset.role == "DATA"),
                    tuple(observations),
                )
            except ValueError as error:
                split_valid = False
                gaps.append(f"DATASET_{dataset}_{error}")
        # Scope markers do not change when a person edits an already-read
        # file. Fence every unique measured file at the end of the whole batch.
        # These stat observations narrow that race; they are not immutable
        # filesystem snapshots and cannot prevent edits after this return.
        changed: dict[uuid.UUID, tuple[BaselineAssetStatus, str]] = {}
        asset_ids: dict[tuple[ProjectSourceScope, ProjectSourceFile], list[uuid.UUID]] = {}
        for asset in request.assets:
            asset_ids.setdefault((asset.source_scope, asset.source_file), []).append(asset.asset_id)
        for key, file_fence in file_fences.items():
            if issue := file_fence.final_issue():
                for asset_id in asset_ids[key]:
                    changed[asset_id] = issue
                    gaps.append(f"ASSET_{asset_id}_{issue[1]}")
        if changed:
            observations = [
                replace(row, status=changed[row.asset_id][0], issue=changed[row.asset_id][1])
                if row.asset_id in changed
                else row
                for row in observations
            ]
            if any(
                asset.asset_id in changed and asset.role in {"DATA", "SPLIT_MANIFEST"}
                for asset in request.assets
            ):
                split_valid = False
                gaps.append("DATA_SPLIT_SOURCE_CHANGED_AFTER_READ")
        return BaselineProbeResult(
            CHECKER_VERSION, checker_sha, tuple(observations), tuple(gaps), split_valid
        )
