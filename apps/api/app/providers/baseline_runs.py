"""Local Docker execution candidates with frozen scope and bounded retained output.

Only a configured immutable local image is used. No pull, build, install, network,
owner project mount, credentials, or scientific qualification is provided here.
Local volumes are readonly to the user container, not immutable image snapshots.
"""

import asyncio
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tarfile
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from app.domain.baseline_runs import (
    PYTHON_EXEC_PROFILE_V1,
    RUN_INPUT_MARKER,
    RUN_INPUT_VERIFIER_V1,
    RUN_OUTPUT_COLLECTOR_V1,
    BaselineInputSeal,
    BaselineRunArtifact,
    BaselineRunInput,
    BaselineRunProjection,
    BaselineRunProvider,
    BaselineRunReceipt,
    BaselineRunRequest,
    BaselineRunStatus,
    BaselineRuntimeEvidence,
    CancelRequested,
    CreatedCallback,
    run_collector_command_sha256,
    run_command_sha256,
    run_container_name,
    run_helper_container_name,
    run_input_manifest_bytes,
    run_input_manifest_sha256,
    run_projection_sha256,
    run_request_sha256,
    run_verifier_command_sha256,
    run_volume_name,
)
from app.domain.baselines import BaselineProbeAsset, BaselineProbeRequest, DatasetSplitManifestV1
from app.domain.project_sources import ProjectSourceScope
from app.errors import DomainError
from app.providers.baselines import _json, _ScopeFence
from app.providers.project_sources import (
    LocalProjectSourceWorkspaceProvider,
    _parts,
    _path,
    _signature,
)

MAX_JSON = 4 * 1024 * 1024
IDENTITY = re.compile(r"[a-f0-9]{64}\Z")
IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")
INPUT_MARKER = RUN_INPUT_MARKER
EXEC_PROFILE = PYTHON_EXEC_PROFILE_V1
VERIFY_INPUT = RUN_INPUT_VERIFIER_V1


@dataclass(frozen=True)
class DockerCommandResult:
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""


class DockerCommandError(Exception):
    def __init__(self, code: str, prefix: bytes = b"") -> None:
        super().__init__(code)
        self.code, self.prefix = code, prefix


class DockerCLI(Protocol):
    async def call(
        self, argv: tuple[str, ...], *, env: dict[str, str], timeout: float, max_bytes: int
    ) -> DockerCommandResult: ...


class NativeDockerCLI:
    async def call(
        self, argv: tuple[str, ...], *, env: dict[str, str], timeout: float, max_bytes: int
    ) -> DockerCommandResult:
        process: asyncio.subprocess.Process | None = None
        chunks: list[bytes] = []
        size = 0

        async def read(stream: asyncio.StreamReader | None) -> bytes:
            nonlocal size
            output = bytearray()
            if stream is not None:
                while part := await stream.read(65536):
                    size += len(part)
                    if size > max_bytes:
                        raise DockerCommandError(
                            "DOCKER_CLI_OUTPUT_LIMIT", b"".join(chunks)[:max_bytes]
                        )
                    output.extend(part)
                    chunks.append(part)
            return bytes(output)

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            async with asyncio.timeout(timeout):
                stdout, stderr = await asyncio.gather(read(process.stdout), read(process.stderr))
                code = await process.wait()
            return DockerCommandResult(code, stdout, stderr)
        except TimeoutError:
            raise DockerCommandError("DOCKER_CLI_TIMEOUT") from None
        except OSError:
            raise DockerCommandError("DOCKER_CLI_UNAVAILABLE") from None
        finally:
            if process is not None and process.returncode is None:
                # This is only this provider's CLI child. Container outcome is
                # separately inspected/stopped; killing a CLI is not evidence.
                process.kill()
                await process.wait()


def _bytes(value: object) -> bytes:
    def default(item: object) -> str:
        if isinstance(item, uuid.UUID):
            return str(item)
        if isinstance(item, datetime):
            return item.isoformat()
        raise TypeError("Unsupported runner receipt value")

    return json.dumps(
        value,
        default=default,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def _fail(code: str) -> DomainError:
    return DomainError(
        code, "Frozen local runner scope or observed isolation could not be verified", 409
    )


class LocalBaselineInputProjectionProvider:
    def __init__(
        self, source_resolver: Callable[[ProjectSourceScope], LocalProjectSourceWorkspaceProvider]
    ) -> None:
        self.resolver = source_resolver

    def _read_source(
        self, asset: BaselineProbeAsset, *, destination: Path | None = None, limit: int
    ) -> tuple[bytes, tuple[int, int, int, int, int], _ScopeFence]:
        fence = _ScopeFence.create(self.resolver(asset.source_scope), asset)
        path = fence.path(asset)
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise _fail("BASELINE_RUN_SOURCE_LIMIT_OR_TYPE")
        digest = hashlib.sha256()
        size = 0
        content = bytearray()
        output = destination.open("xb") if destination is not None else None
        try:
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                if _signature(opened) != _signature(before):
                    raise _fail("BASELINE_RUN_SOURCE_CHANGED")
                while chunk := stream.read(65536):
                    size += len(chunk)
                    if size > limit:
                        raise _fail("BASELINE_RUN_SOURCE_CHANGED")
                    digest.update(chunk)
                    if output is not None:
                        output.write(chunk)
                    else:
                        content.extend(chunk)
                after = os.fstat(stream.fileno())
            _path(path)
            current = path.lstat()
            if (
                _signature(opened) != _signature(after)
                or _signature(current) != _signature(after)
                or (digest.hexdigest(), size)
                != (asset.source_file.sha256, asset.source_file.size_bytes)
            ):
                raise _fail("BASELINE_RUN_SOURCE_CHANGED")
            fence.finish()
            return bytes(content), _signature(current), fence
        finally:
            if output is not None:
                output.close()

    async def project_inputs(self, request: BaselineProbeRequest) -> BaselineRunProjection:
        return await asyncio.to_thread(self._project, request)

    def _project(self, request: BaselineProbeRequest) -> BaselineRunProjection:
        if not request.assets or any(
            asset.source_scope.owner_id != request.owner_id
            or asset.source_scope.project_id != request.project_id
            for asset in request.assets
        ):
            raise _fail("BASELINE_RUN_SOURCE_SCOPE_INVALID")
        inputs = []
        manifests = []
        test_assets: list[BaselineProbeAsset] = []
        data = {
            (asset.dataset_version_id, asset.source_file.path): asset
            for asset in request.assets
            if asset.role == "DATA"
        }
        if len(data) != sum(asset.role == "DATA" for asset in request.assets):
            raise _fail("BASELINE_RUN_DATA_AMBIGUOUS")
        dataset_ids = set()
        for asset in request.assets:
            if asset.role in {"DATA", "SPLIT_MANIFEST"}:
                continue
            inputs.append(
                BaselineRunInput(
                    asset.asset_id,
                    asset.role,
                    asset.source_scope,
                    asset.source_file,
                    "sources/" + asset.source_scope.plan_id.hex + "/" + asset.source_file.path,
                )
            )
        for asset in request.assets:
            if asset.role != "SPLIT_MANIFEST":
                continue
            if asset.dataset_version_id in dataset_ids:
                raise _fail("BASELINE_RUN_DATA_AMBIGUOUS")
            dataset_ids.add(asset.dataset_version_id)
            content, _, _ = self._read_source(asset, limit=MAX_JSON)
            raw_source = _json(content)
            if (
                not isinstance(raw_source, dict)
                or type(raw_source.get("schema_version")) is not int
            ):
                raise _fail("BASELINE_RUN_SPLIT_INVALID")
            manifest = DatasetSplitManifestV1.model_validate_json(content, strict=True)
            if manifest.dataset_version_id != asset.dataset_version_id or {
                part.name for part in manifest.splits
            } != {"TRAIN", "VALIDATION", "TEST"}:
                raise _fail("BASELINE_RUN_SPLIT_INVALID")
            paths = set()
            sample_ids = set()
            groups: dict[str, str] = {}
            parts = []
            for split in manifest.splits:
                samples = []
                for sample in split.samples:
                    key = (asset.dataset_version_id, sample.path)
                    source = data.get(key)
                    if (
                        source is None
                        or key in paths
                        or sample.sample_id in sample_ids
                        or (sample.sha256, sample.size_bytes)
                        != (source.source_file.sha256, source.source_file.size_bytes)
                        or (sample.group_id in groups and groups[sample.group_id] != split.name)
                    ):
                        raise _fail("BASELINE_RUN_SPLIT_INVALID")
                    paths.add(key)
                    sample_ids.add(sample.sample_id)
                    groups[sample.group_id] = split.name
                    if split.name == "TEST":
                        test_assets.append(source)
                        continue
                    destination = "data/" + manifest.dataset_version_id.hex + "/" + sample.path
                    inputs.append(
                        BaselineRunInput(
                            source.asset_id,
                            "DATA",
                            source.source_scope,
                            source.source_file,
                            destination,
                            split.name,
                            manifest.dataset_version_id,
                            sample.sample_id,
                            sample.group_id,
                        )
                    )
                    samples.append({**sample.model_dump(), "path": destination})
                if split.name != "TEST":
                    parts.append({"name": split.name, "samples": samples})
            if paths != {key for key in data if key[0] == asset.dataset_version_id}:
                raise _fail("BASELINE_RUN_SPLIT_INVALID")
            projected = _bytes(
                {
                    "schema": "baseline-run-split-projection-v1",
                    "dataset_version_id": manifest.dataset_version_id,
                    "source_manifest_sha256": asset.source_file.sha256,
                    "splits": parts,
                }
            )
            manifests.append(
                BaselineRunInput(
                    asset.asset_id,
                    "SPLIT_MANIFEST",
                    asset.source_scope,
                    asset.source_file,
                    "data/" + manifest.dataset_version_id.hex + "/split-manifest.json",
                    dataset_version_id=manifest.dataset_version_id,
                    projected_content=projected,
                )
            )
        if dataset_ids != set(request.dataset_version_ids):
            raise _fail("BASELINE_RUN_SPLIT_INVALID")
        result = tuple(inputs + manifests)
        selected_ids = {item.asset_id for item in result}
        for asset in request.assets:
            if asset.asset_id not in selected_ids:
                continue
            if any(
                (
                    asset.source_scope.root_fingerprint,
                    asset.source_scope.relative_path,
                    asset.source_file.path,
                )
                == (
                    test.source_scope.root_fingerprint,
                    test.source_scope.relative_path,
                    test.source_file.path,
                )
                or (asset.attachment_id is not None and asset.attachment_id == test.attachment_id)
                or (asset.source_file.sha256, asset.source_file.size_bytes)
                == (test.source_file.sha256, test.source_file.size_bytes)
                for test in test_assets
            ):
                raise _fail("BASELINE_RUN_TEST_ALIAS_REJECTED")
        digest = run_projection_sha256(result)
        return BaselineRunProjection(result, digest)


class UnconfiguredBaselineRunProvider(LocalBaselineInputProjectionProvider, BaselineRunProvider):
    def __init__(
        self,
        source_resolver: Callable[[ProjectSourceScope], LocalProjectSourceWorkspaceProvider],
        *,
        reason: str = "RUNNER_NOT_CONFIGURED",
    ) -> None:
        super().__init__(source_resolver)
        self.reason = reason

    async def runtime(self) -> BaselineRuntimeEvidence:
        return BaselineRuntimeEvidence(False, "", None, None, (self.reason,), datetime.now(UTC))

    async def execute(
        self,
        request: BaselineRunRequest,
        *,
        on_created: CreatedCallback | None = None,
        cancel_requested: CancelRequested | None = None,
    ) -> BaselineRunReceipt:
        raise _fail("BASELINE_RUN_UNAVAILABLE")

    async def inspect(self, request: BaselineRunRequest, container_id: str) -> BaselineRunReceipt:
        raise _fail("BASELINE_RUN_UNAVAILABLE")

    async def cancel(self, request: BaselineRunRequest, container_id: str) -> BaselineRunReceipt:
        raise _fail("BASELINE_RUN_UNAVAILABLE")

    async def open_artifact(self, request: BaselineRunRequest, path: str) -> AsyncIterator[bytes]:
        raise _fail("BASELINE_RUN_UNAVAILABLE")
        yield b""  # Async iterator shape; unavailable providers never yield data.


class LocalDockerBaselineRunProvider(LocalBaselineInputProjectionProvider, BaselineRunProvider):
    def __init__(
        self,
        *,
        docker_executable: Path,
        docker_host: str,
        image_id: str,
        daemon_id: str,
        run_root: Path,
        source_resolver: Callable[[ProjectSourceScope], LocalProjectSourceWorkspaceProvider],
        cli: DockerCLI | None = None,
    ) -> None:
        if (
            not docker_executable.is_absolute()
            or docker_executable.name.casefold() not in {"docker", "docker.exe"}
            or not IMAGE.fullmatch(image_id)
            or not daemon_id
            or len(daemon_id) > 128
            or docker_host
            not in {
                "npipe:////./pipe/docker_engine",
                "npipe:////./pipe/dockerDesktopLinuxEngine",
                "unix:///var/run/docker.sock",
            }
            or not run_root.is_absolute()
            or ".." in run_root.parts
        ):
            raise _fail("BASELINE_RUN_CONFIGURATION_INVALID")
        _path(docker_executable)
        _path(run_root)
        self.executable, self.host, self.image, self.daemon, self.root = (
            docker_executable,
            docker_host,
            image_id,
            daemon_id,
            run_root,
        )
        self.resolver, self.cli = source_resolver, cli or NativeDockerCLI()

    def _env(self) -> dict[str, str]:
        blocked = (
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_CONFIG",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
            "DOCKER_API_VERSION",
            "DOCKER_CUSTOM_HEADERS",
        )
        if any(os.environ.get(name) for name in blocked):
            raise DockerCommandError("DOCKER_ENV_OVERRIDE_REJECTED")
        allowed = {
            "SYSTEMROOT",
            "WINDIR",
            "PATH",
            "PATHEXT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "HOME",
            "COMSPEC",
        }
        return {key: value for key, value in os.environ.items() if key.upper() in allowed}

    async def _call(
        self, *args: str, timeout: float = 20, max_bytes: int = MAX_JSON, required: bool = True
    ) -> DockerCommandResult:
        _path(self.executable)
        if not self.executable.is_file():
            raise DockerCommandError("DOCKER_CLI_UNAVAILABLE")
        config = self.root / ".docker-no-auth"
        _path(config)
        if config.exists() and (not config.is_dir() or any(config.iterdir())):
            raise DockerCommandError("DOCKER_CONFIG_OVERRIDE_REJECTED")
        result = await self.cli.call(
            (str(self.executable), "--host", self.host, "--config", str(config), *args),
            env=self._env(),
            timeout=timeout,
            max_bytes=max_bytes,
        )
        if (
            type(result.returncode) is not int
            or len(result.stdout) + len(result.stderr) > max_bytes
        ):
            raise DockerCommandError("DOCKER_CLI_OUTPUT_LIMIT")
        if required and result.returncode:
            raise DockerCommandError("DOCKER_CLI_REJECTED")
        return result

    async def _object(self, *args: str) -> dict[str, Any]:
        raw = _json((await self._call(*args)).stdout)
        if isinstance(raw, list):
            if len(raw) != 1:
                raise DockerCommandError("DOCKER_RESPONSE_INVALID")
            raw = raw[0]
        if not isinstance(raw, dict):
            raise DockerCommandError("DOCKER_RESPONSE_INVALID")
        return raw

    async def runtime(self) -> BaselineRuntimeEvidence:
        try:
            info = await self._object("info", "--format", "{{json .}}")
            image = await self._object("image", "inspect", self.image)
            if (
                info.get("OSType") != "linux"
                or info.get("ID") != self.daemon
                or image.get("Id") != self.image
                or image.get("Os") != "linux"
            ):
                raise DockerCommandError("DOCKER_IDENTITY_CHANGED")
            if not all(
                info.get(flag) is True
                for flag in ("MemoryLimit", "SwapLimit", "CpuCfsQuota", "PidsLimit")
            ) or "runc" not in info.get("Runtimes", {}):
                raise DockerCommandError("DOCKER_RESOURCE_LIMITS_UNAVAILABLE")
            if not isinstance(image.get("Config"), dict) or image["Config"].get("Volumes"):
                raise DockerCommandError("DOCKER_IMAGE_EXTRA_VOLUMES_REJECTED")
            return BaselineRuntimeEvidence(
                True, self.host, self.daemon, self.image, (), datetime.now(UTC)
            )
        except (DockerCommandError, DomainError, ValueError, OSError, TypeError):
            return BaselineRuntimeEvidence(
                False,
                self.host,
                None,
                None,
                ("LOCAL_DOCKER_RUNTIME_UNVERIFIED",),
                datetime.now(UTC),
            )

    def _validate(self, request: BaselineRunRequest) -> None:
        limits = request.limits
        integers = asdict(limits)
        if (
            request.profile != "PYTHON_SCRIPT_V1"
            or request.image_id != self.image
            or request.daemon_id != self.daemon
            or any(
                not IDENTITY.fullmatch(value)
                for value in (request.version_sha256, request.request_sha256, request.grant_sha256)
            )
            or run_request_sha256(request) != request.request_sha256
            or not request.inputs
            or len(request.inputs) > limits.max_input_files
            or any(type(value) is not int or value <= 0 for value in integers.values())
            or limits.timeout_seconds > 3600
            or not 100 <= limits.cpu_millicores <= 8000
            or not 16 * 1024 * 1024 <= limits.memory_bytes <= 8 * 1024**3
            or not 4 <= limits.pids <= 256
            or limits.max_input_bytes > 1024**3
            or limits.max_input_files > 10000
            or limits.max_output_bytes > 256 * 1024 * 1024
            or limits.max_log_bytes > 16 * 1024 * 1024
            or limits.max_output_files > 1000
        ):
            raise _fail("BASELINE_RUN_SCOPE_INVALID")
        paths: dict[tuple[str, ...], BaselineRunInput] = {}
        assets = set()
        for item in request.inputs:
            parts = _parts(item.relative_path)
            folded = tuple(part.casefold() for part in parts)
            if item.relative_path == INPUT_MARKER or item.asset_id in assets or folded in paths:
                raise _fail("BASELINE_RUN_INPUT_COLLISION")
            assets.add(item.asset_id)
            paths[folded] = item
            if (
                item.source_scope.owner_id != request.owner_id
                or item.source_scope.project_id != request.project_id
                or item.role
                not in {
                    "CODE",
                    "CONFIG",
                    "ENVIRONMENT_LOCK",
                    "EVALUATOR",
                    "WEIGHTS",
                    "DATA",
                    "SPLIT_MANIFEST",
                }
                or (
                    item.role == "DATA"
                    and (
                        item.dataset_split not in {"TRAIN", "VALIDATION"}
                        or not item.dataset_version_id
                        or not item.sample_id
                        or not item.group_id
                    )
                )
                or (item.role != "DATA" and item.dataset_split is not None)
                or (item.role == "SPLIT_MANIFEST") != (item.projected_content is not None)
            ):
                raise _fail("BASELINE_RUN_TEST_OR_UNPROJECTED_INPUT_REJECTED")
            if item.projected_content is not None:
                self._validate_projection(item, request.inputs)
        if any(any(path[:length] in paths for length in range(1, len(path))) for path in paths):
            raise _fail("BASELINE_RUN_INPUT_COLLISION")
        entries = [item for item in request.inputs if item.asset_id == request.entry_asset_id]
        if (
            len(entries) != 1
            or entries[0].role not in {"CODE", "EVALUATOR"}
            or not entries[0].relative_path.endswith(".py")
        ):
            raise _fail("BASELINE_RUN_ENTRY_INVALID")
        configs = [
            item
            for item in request.inputs
            if item.asset_id == request.config_asset_id and item.role == "CONFIG"
        ]
        if (
            len(configs) != 1
            or type(request.random_seed) is not int
            or not 0 <= request.random_seed < 2**32
        ):
            raise _fail("BASELINE_RUN_CONFIG_OR_SEED_INVALID")

    def _validate_projection(
        self, item: BaselineRunInput, inputs: tuple[BaselineRunInput, ...]
    ) -> None:
        if item.projected_content is None or len(item.projected_content) > MAX_JSON:
            raise _fail("BASELINE_RUN_PROJECTION_INVALID")
        raw = _json(item.projected_content)
        if (
            not isinstance(raw, dict)
            or set(raw) != {"schema", "dataset_version_id", "source_manifest_sha256", "splits"}
            or raw["schema"] != "baseline-run-split-projection-v1"
            or raw["dataset_version_id"] != str(item.dataset_version_id)
            or raw["source_manifest_sha256"] != item.source_file.sha256
        ):
            raise _fail("BASELINE_RUN_PROJECTION_INVALID")
        seen = set()
        names = set()
        expected = {
            entry.relative_path: entry
            for entry in inputs
            if entry.role == "DATA" and entry.dataset_version_id == item.dataset_version_id
        }
        for split in raw["splits"]:
            if (
                not isinstance(split, dict)
                or set(split) != {"name", "samples"}
                or split["name"] not in {"TRAIN", "VALIDATION"}
                or split["name"] in names
                or not split["samples"]
            ):
                raise _fail("BASELINE_RUN_PROJECTION_INVALID")
            names.add(split["name"])
            for sample in split["samples"]:
                if not isinstance(sample, dict) or set(sample) != {
                    "sample_id",
                    "group_id",
                    "path",
                    "sha256",
                    "size_bytes",
                }:
                    raise _fail("BASELINE_RUN_PROJECTION_INVALID")
                entry = expected.get(sample["path"])
                if (
                    entry is None
                    or sample["path"] in seen
                    or (
                        sample["sample_id"],
                        sample["group_id"],
                        sample["sha256"],
                        sample["size_bytes"],
                        split["name"],
                    )
                    != (
                        entry.sample_id,
                        entry.group_id,
                        entry.source_file.sha256,
                        entry.source_file.size_bytes,
                        entry.dataset_split,
                    )
                ):
                    raise _fail("BASELINE_RUN_PROJECTION_INVALID")
                seen.add(sample["path"])
        if names != {"TRAIN", "VALIDATION"} or seen != set(expected):
            raise _fail("BASELINE_RUN_PROJECTION_INVALID")

    def _job(self, request: BaselineRunRequest) -> Path:
        # Owner + globally unique job keep Windows paths bounded. Project and
        # full UUID identities remain bound by the canonical request marker.
        return self.root / request.owner_id.hex / request.job_id.hex

    def _entry(self, request: BaselineRunRequest) -> tuple[str, str]:
        entry = next(item for item in request.inputs if item.asset_id == request.entry_asset_id)
        path = "/input/" + entry.relative_path
        return path, str(PurePosixPath(path).parent)

    def _command_hash(self, request: BaselineRunRequest) -> str:
        return run_command_sha256(request)

    def _name(self, request: BaselineRunRequest) -> str:
        return run_container_name(request)

    def _keepalive(self, request: BaselineRunRequest) -> str:
        return "import time; time.sleep(" + str(request.limits.timeout_seconds + 10) + ")"

    def _receipt(
        self,
        request: BaselineRunRequest,
        status: BaselineRunStatus,
        *,
        container: str | None = None,
        manifest: str | None = None,
        exit_code: int | None = None,
        logs: str = "",
        artifacts: tuple[BaselineRunArtifact, ...] = (),
        issues: tuple[str, ...] = (),
        began: datetime | None = None,
        stopped: bool | None = None,
        seal: BaselineInputSeal | None = None,
    ) -> BaselineRunReceipt:
        return BaselineRunReceipt(
            request.job_id,
            status,
            container,
            self._name(request),
            self.image,
            self.daemon,
            self._command_hash(request),
            manifest,
            exit_code,
            logs,
            artifacts,
            began or datetime.now(UTC),
            datetime.now(UTC),
            issues,
            input_sealed=seal is not None and seal.helper_removed and seal.mounted_readonly,
            container_stopped=stopped,
            input_seal=seal,
        )

    def _stage(
        self, request: BaselineRunRequest
    ) -> tuple[
        Path, str, list[tuple[_ScopeFence, BaselineProbeAsset, tuple[int, int, int, int, int]]]
    ]:
        self._validate(request)
        job = self._job(request)
        _path(job)
        if job.exists():
            raise _fail("BASELINE_RUN_REPLAY_REJECTED")
        job.mkdir(parents=True, mode=0o700, exist_ok=False)
        inputs = job / "inputs"
        # The private job parent is 0700; transferred input directories/files
        # must still be readable by the fixed nonroot container UID.
        inputs.mkdir(mode=0o755)
        snapshots = []
        files = []
        total = 0
        projection_sources: dict[uuid.UUID, tuple[tuple[int, int, int, int, int], _ScopeFence]] = {}
        test_bytes: set[tuple[str, int]] = set()
        for item in request.inputs:
            if item.projected_content is None:
                continue
            asset = BaselineProbeAsset(
                item.asset_id,
                item.role,
                item.dataset_version_id,
                item.source_scope,
                item.source_file,
            )
            original, signature, fence = self._read_source(asset, limit=MAX_JSON)
            raw_source = _json(original)
            if (
                not isinstance(raw_source, dict)
                or type(raw_source.get("schema_version")) is not int
            ):
                raise _fail("BASELINE_RUN_SPLIT_INVALID")
            source = DatasetSplitManifestV1.model_validate_json(original, strict=True)
            if source.dataset_version_id != item.dataset_version_id or {
                split.name for split in source.splits
            } != {"TRAIN", "VALIDATION", "TEST"}:
                raise _fail("BASELINE_RUN_TEST_OR_CHANGED_PROJECTION")
            expected = {
                (sample.path, sample.sha256, sample.size_bytes): (
                    split.name,
                    sample.sample_id,
                    sample.group_id,
                )
                for split in source.splits
                for sample in split.samples
            }
            selected = [
                entry
                for entry in request.inputs
                if entry.role == "DATA" and entry.dataset_version_id == item.dataset_version_id
            ]
            if any(
                expected.get(
                    (entry.source_file.path, entry.source_file.sha256, entry.source_file.size_bytes)
                )
                != (entry.dataset_split, entry.sample_id, entry.group_id)
                for entry in selected
            ):
                raise _fail("BASELINE_RUN_TEST_OR_CHANGED_PROJECTION")
            test_bytes.update(
                (sample.sha256, sample.size_bytes)
                for split in source.splits
                if split.name == "TEST"
                for sample in split.samples
            )
            projection_sources[item.asset_id] = (signature, fence)
        if any(
            (item.source_file.sha256, item.source_file.size_bytes) in test_bytes
            for item in request.inputs
        ):
            raise _fail("BASELINE_RUN_TEST_ALIAS_REJECTED")
        for item in request.inputs:
            _path(inputs)
            destination = inputs.joinpath(*_parts(item.relative_path))
            destination.parent.mkdir(parents=True, exist_ok=True)
            asset = BaselineProbeAsset(
                item.asset_id,
                item.role,
                item.dataset_version_id,
                item.source_scope,
                item.source_file,
            )
            if item.projected_content is not None:
                signature, fence = projection_sources[item.asset_id]
                destination.write_bytes(item.projected_content)
                sha, size = (
                    hashlib.sha256(item.projected_content).hexdigest(),
                    len(item.projected_content),
                )
            else:
                _, signature, fence = self._read_source(
                    asset, destination=destination, limit=request.limits.max_input_bytes - total
                )
                sha, size = item.source_file.sha256, item.source_file.size_bytes
            snapshots.append((fence, asset, signature))
            destination.chmod(0o444)
            total += size
            if total > request.limits.max_input_bytes:
                raise _fail("BASELINE_RUN_INPUT_LIMIT")
            files.append(
                {
                    "path": item.relative_path,
                    "sha256": sha,
                    "size_bytes": size,
                    "role": item.role,
                    "dataset_split": item.dataset_split,
                }
            )
        self._source_fence(snapshots)
        manifest = run_input_manifest_bytes(request)
        compiled = _json(manifest)
        if not isinstance(compiled, dict) or compiled.get("files") != files:
            raise _fail("BASELINE_RUN_STAGED_MANIFEST_CHANGED")
        (inputs / INPUT_MARKER).write_bytes(manifest)
        (inputs / INPUT_MARKER).chmod(0o444)
        (job / "request.json").write_bytes(
            _bytes(
                {
                    "request_sha256": request.request_sha256,
                    "input_manifest_sha256": hashlib.sha256(manifest).hexdigest(),
                }
            )
        )
        return job, hashlib.sha256(manifest).hexdigest(), snapshots

    def _source_fence(
        self,
        snapshots: list[tuple[_ScopeFence, BaselineProbeAsset, tuple[int, int, int, int, int]]],
    ) -> None:
        for fence, asset, signature in snapshots:
            if _signature(fence.path(asset).lstat()) != signature:
                raise _fail("BASELINE_RUN_SOURCE_CHANGED")
            fence.finish()

    def _limits_args(self, request: BaselineRunRequest) -> list[str]:
        limits = request.limits
        return [
            "--pull=never",
            "--read-only",
            "--network=none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--runtime=runc",
            "--cpus=" + str(limits.cpu_millicores / 1000),
            "--memory=" + str(limits.memory_bytes),
            "--memory-swap=" + str(limits.memory_bytes),
            "--pids-limit=" + str(limits.pids),
            "--ipc=none",
            "--no-healthcheck",
            "--log-driver=local",
            "--log-opt=max-size=" + str(limits.max_log_bytes),
            "--log-opt=max-file=1",
            "--log-opt=compress=false",
            "--label=researchos.job=" + str(request.job_id),
            "--label=researchos.owner=" + str(request.owner_id),
            "--label=researchos.request=" + request.request_sha256,
        ]

    async def _verify_container(
        self,
        request: BaselineRunRequest,
        container_id: str,
        *,
        helper: bool = False,
        manifest: str | None = None,
    ) -> dict[str, Any]:
        expected_name = self._name(request) + ("-input-helper" if helper else "")
        if not IDENTITY.fullmatch(container_id) and container_id != expected_name:
            raise DockerCommandError("DOCKER_CONTAINER_ID_INVALID")
        raw = await self._object("container", "inspect", container_id)
        config, host = raw.get("Config", {}), raw.get("HostConfig", {})
        if (
            not isinstance(config, dict)
            or not isinstance(host, dict)
            or not isinstance(raw.get("Id"), str)
            or not IDENTITY.fullmatch(raw["Id"])
        ):
            raise DockerCommandError("DOCKER_RESPONSE_INVALID")
        labels = {
            "researchos.job": str(request.job_id),
            "researchos.owner": str(request.owner_id),
            "researchos.request": request.request_sha256,
        }
        mount = {
            "Type": "volume",
            "Source": run_volume_name(request),
            "Target": "/input",
            "ReadOnly": not helper,
        }
        mounts = host.get("Mounts")
        command = (
            ["-I", "-B", "-c", VERIFY_INPUT, manifest]
            if helper
            else ["-I", "-B", "-c", self._keepalive(request)]
        )
        if (
            (IDENTITY.fullmatch(container_id) and raw.get("Id") != container_id)
            or raw.get("Name") != "/" + expected_name
            or raw.get("Image") != self.image
            or config.get("Image") != self.image
            or config.get("Entrypoint") != ["python"]
            or config.get("Cmd") != command
            or config.get("User") != ("0:0" if helper else "65534:65534")
            or any(config.get("Labels", {}).get(key) != value for key, value in labels.items())
            or host.get("ReadonlyRootfs") is not True
            or host.get("NetworkMode") != "none"
            or host.get("Privileged") is not False
            or host.get("CapDrop") != ["ALL"]
            or host.get("CapAdd")
            or host.get("SecurityOpt") != ["no-new-privileges:true"]
            or host.get("Runtime") != "runc"
            or host.get("NanoCpus") != request.limits.cpu_millicores * 1000000
            or host.get("Memory") != request.limits.memory_bytes
            or host.get("MemorySwap") != request.limits.memory_bytes
            or host.get("PidsLimit") != request.limits.pids
            or host.get("IpcMode") != "none"
            or host.get("PidMode") not in {"", None}
            or host.get("UTSMode") not in {"", None}
            or any(
                host.get(key)
                for key in (
                    "Binds",
                    "Devices",
                    "DeviceRequests",
                    "PortBindings",
                    "VolumesFrom",
                    "ExtraHosts",
                )
            )
            or host.get("PublishAllPorts") is True
            or host.get("RestartPolicy", {}).get("Name") not in {"", "no"}
            or not isinstance(mounts, list)
            or len(mounts) != 1
            # Docker omits false ReadOnly in helper Mount JSON. Main must still
            # explicitly be readonly; actual Mounts.RW is checked separately.
            or any(
                mounts[0].get(key, False if key == "ReadOnly" and helper else None) != value
                for key, value in mount.items()
            )
            or host.get("LogConfig")
            != {
                "Type": "local",
                "Config": {
                    "max-size": str(request.limits.max_log_bytes),
                    "max-file": "1",
                    "compress": "false",
                },
            }
        ):
            raise DockerCommandError("DOCKER_ISOLATION_UNVERIFIED")
        actual_mounts = raw.get("Mounts")
        if (
            not isinstance(actual_mounts, list)
            or len(actual_mounts) != 1
            or actual_mounts[0].get("Type") != "volume"
            or actual_mounts[0].get("Name") != mount["Source"]
            or actual_mounts[0].get("Destination") != "/input"
            or actual_mounts[0].get("RW") is not helper
        ):
            raise DockerCommandError("DOCKER_ACTUAL_MOUNTS_UNVERIFIED")
        if not helper:
            tmpfs = host.get("Tmpfs", {})
            if tmpfs != {
                "/output": self._output_tmpfs(request),
                "/tmp": "rw,noexec,nosuid,nodev,size=4194304,mode=1777",
            }:
                raise DockerCommandError("DOCKER_OUTPUT_BOUND_UNVERIFIED")
        return raw

    def _output_tmpfs(self, request: BaselineRunRequest) -> str:
        return (
            "rw,noexec,nosuid,nodev,size="
            + str(request.limits.max_output_bytes)
            + ",nr_inodes="
            + str(request.limits.max_output_files + 32)
            + ",mode=1777"
        )

    async def _stop(self, request: BaselineRunRequest, container: str) -> bool:
        try:
            if not (await self.runtime()).available:
                return False
            verified = await self._verify_container(request, container)
            actual_id = verified["Id"]
            if verified.get("State", {}).get("Paused") is True:
                await self._call("container", "unpause", actual_id)
                observed = await self._verify_container(request, actual_id)
                if observed.get("State", {}).get("Paused") is not False:
                    return False
            await self._call("container", "stop", "--time=1", actual_id, timeout=10)
            raw = await self._verify_container(request, actual_id)
            state = raw.get("State", {})
            return (
                state.get("Running") is False
                and type(state.get("Pid")) is int
                and state.get("Pid") == 0
                and type(state.get("ExitCode")) is int
                and self._resources_stopped(await self._resource_closure(request))
            )
        except (DockerCommandError, DomainError, ValueError, OSError):
            return False

    async def _volume(
        self, request: BaselineRunRequest, job: Path, manifest: str
    ) -> BaselineInputSeal:
        name = run_volume_name(request)
        result = await self._call(
            "volume",
            "create",
            "--driver=local",
            "--label=researchos.job=" + str(request.job_id),
            "--label=researchos.request=" + request.request_sha256,
            name,
        )
        if result.stdout.decode().strip() != name:
            raise DockerCommandError("DOCKER_VOLUME_CREATE_UNKNOWN")
        volume = await self._object("volume", "inspect", name)
        if (
            volume.get("Name") != name
            or volume.get("Driver") != "local"
            or volume.get("Options")
            or volume.get("Labels", {}).get("researchos.request") != request.request_sha256
            or volume.get("Labels", {}).get("researchos.job") != str(request.job_id)
        ):
            raise DockerCommandError("DOCKER_VOLUME_IDENTITY_UNVERIFIED")
        helper_name = run_helper_container_name(request)
        created = await self._call(
            "container",
            "create",
            "--name=" + helper_name,
            *self._limits_args(request),
            "--user=0:0",
            "--mount=type=volume,source=" + name + ",target=/input",
            "--entrypoint=python",
            self.image,
            "-I",
            "-B",
            "-c",
            VERIFY_INPUT,
            manifest,
        )
        helper = created.stdout.decode().strip()
        await self._verify_container(request, helper, helper=True, manifest=manifest)
        (job / "resources.json").write_bytes(
            _bytes({"volume": name, "helper_id": helper, "helper_name": helper_name})
        )
        await self._call(
            "container", "cp", str(job / "inputs") + "/.", helper + ":/input/", timeout=120
        )
        checked = await self._call(
            "container",
            "start",
            "--attach",
            helper,
            timeout=min(request.limits.timeout_seconds, 120),
        )
        raw = await self._verify_container(request, helper, helper=True, manifest=manifest)
        data = _json(checked.stdout)
        if (
            raw.get("State", {}).get("Running") is not False
            or raw.get("State", {}).get("ExitCode") != 0
            or data != {"manifest_sha256": manifest, "verified_files": len(request.inputs)}
        ):
            raise DockerCommandError("DOCKER_INPUT_VOLUME_HASH_UNVERIFIED")
        removed = await self._call("container", "rm", helper)
        if removed.stdout.decode().strip() != helper:
            raise DockerCommandError("DOCKER_INPUT_HELPER_REMOVAL_UNKNOWN")
        return BaselineInputSeal(
            name,
            manifest,
            self.image,
            run_verifier_command_sha256(request),
            helper,
            True,
            False,
        )

    async def _resource_closure(self, request: BaselineRunRequest) -> dict[str, dict[str, Any]]:
        result = await self._call(
            "container",
            "ls",
            "--all",
            "--no-trunc",
            "--filter=label=researchos.job=" + str(request.job_id),
            "--format={{json .}}",
        )
        names = {run_container_name(request), run_helper_container_name(request)}
        rows = result.stdout.splitlines()
        if len(rows) > 2:
            raise DockerCommandError("DOCKER_JOB_EXTRA_RESOURCES_UNKNOWN")
        resources = {}
        for line in rows:
            summary = _json(line)
            if (
                not isinstance(summary, dict)
                or summary.get("Names") not in names
                or not isinstance(summary.get("ID"), str)
                or summary["Names"] in resources
            ):
                raise DockerCommandError("DOCKER_JOB_RESOURCES_INVALID")
            helper = summary["Names"] == run_helper_container_name(request)
            resources[summary["Names"]] = await self._verify_container(
                request,
                summary["ID"],
                helper=helper,
                manifest=run_input_manifest_sha256(request) if helper else None,
            )
        return resources

    def _resources_stopped(self, resources: dict[str, dict[str, Any]]) -> bool:
        return all(
            isinstance(raw.get("State"), dict)
            and raw["State"].get("Running") is False
            and type(raw["State"].get("Pid")) is int
            and raw["State"]["Pid"] == 0
            and type(raw["State"].get("ExitCode")) is int
            for raw in resources.values()
        )

    def _resource_issues(self, resources: dict[str, dict[str, Any]]) -> tuple[str, ...]:
        return tuple(
            "RESOURCE:"
            + name
            + ":"
            + raw["Id"]
            + ":"
            + ("STOPPED" if self._resources_stopped({name: raw}) else "LIVE_OR_UNKNOWN")
            for name, raw in sorted(resources.items())
        )

    def _extract(
        self, request: BaselineRunRequest, job: Path, payload: bytes
    ) -> tuple[BaselineRunArtifact, ...]:
        output = job / "output"
        output.mkdir(exist_ok=False)
        artifacts: list[BaselineRunArtifact] = []
        total = 0
        members = 0
        paths = set()
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            for member in archive:
                members += 1
                if members > request.limits.max_output_files + 32:
                    raise _fail("BASELINE_RUN_OUTPUT_LIMIT")
                name = member.name
                if name in {".", "./"} and member.isdir():
                    continue
                if name.startswith("./"):
                    name = name[2:]
                parts = _parts(name)
                folded = tuple(part.casefold() for part in parts)
                if folded in paths or not (member.isdir() or member.isfile()) or member.size < 0:
                    raise _fail("BASELINE_RUN_OUTPUT_UNSAFE")
                paths.add(folded)
                destination = output.joinpath(*parts)
                _path(destination)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                total += member.size
                if (
                    total > request.limits.max_output_bytes
                    or len(artifacts) >= request.limits.max_output_files
                ):
                    raise _fail("BASELINE_RUN_OUTPUT_LIMIT")
                destination.parent.mkdir(parents=True, exist_ok=True)
                stream = archive.extractfile(member)
                if stream is None:
                    raise _fail("BASELINE_RUN_OUTPUT_UNSAFE")
                digest = hashlib.sha256()
                count = 0
                with stream, destination.open("xb") as file:
                    while chunk := stream.read(65536):
                        count += len(chunk)
                        if count > member.size:
                            raise _fail("BASELINE_RUN_OUTPUT_UNSAFE")
                        digest.update(chunk)
                        file.write(chunk)
                if count != member.size:
                    raise _fail("BASELINE_RUN_OUTPUT_UNSAFE")
                artifacts.append(BaselineRunArtifact("output/" + name, digest.hexdigest(), count))
        return tuple(sorted(artifacts, key=lambda artifact: artifact.path))

    async def _collect_tmpfs(
        self, request: BaselineRunRequest, container: str, job: Path
    ) -> tuple[BaselineRunArtifact, ...]:
        raw = await self._verify_container(request, container)
        if (
            raw.get("State", {}).get("Running") is not True
            or raw.get("State", {}).get("Paused") is not False
        ):
            raise DockerCommandError("BASELINE_RUN_OUTPUT_COLLECTION_UNAVAILABLE")
        command_sha = run_collector_command_sha256(request)
        bound = (
            request.limits.max_output_bytes
            + (request.limits.max_output_files + 32) * 16384
            + MAX_JSON
        )
        result = await self._call(
            "container",
            "exec",
            "--user=65534:65534",
            container,
            "python",
            "-I",
            "-B",
            "-c",
            RUN_OUTPUT_COLLECTOR_V1,
            request.request_sha256,
            command_sha,
            str(request.limits.max_output_files),
            str(request.limits.max_output_bytes),
            timeout=30,
            max_bytes=bound,
            required=False,
        )
        if result.returncode:
            allowed = {
                "BASELINE_RUN_OUTPUT_NOT_QUIESCENT",
                "BASELINE_RUN_OUTPUT_UNSAFE",
                "BASELINE_RUN_OUTPUT_LIMIT",
                "BASELINE_RUN_OUTPUT_CHANGED",
                "BASELINE_RUN_NO_OUTPUT_ARTIFACTS",
                "BASELINE_RUN_OUTPUT_COLLECTION_UNAVAILABLE",
            }
            try:
                error = _json(result.stderr)
            except (ValueError, TypeError):
                error = None
            code = (
                error.get("code")
                if isinstance(error, dict)
                and error.get("schema") == "baseline-collector-error-v1"
                and error.get("request_sha256") == request.request_sha256
                else None
            )
            raise DockerCommandError(
                code if code in allowed else "BASELINE_RUN_OUTPUT_COLLECTION_UNAVAILABLE"
            )
        header_bytes, separator, payload = result.stdout.partition(b"\n")
        if not separator or len(header_bytes) > MAX_JSON:
            raise DockerCommandError("BASELINE_RUN_OUTPUT_ENVELOPE_INVALID")
        header = _json(header_bytes)
        if (
            not isinstance(header, dict)
            or set(header)
            != {"schema", "request_sha256", "collector_command_sha256", "quiescent", "files"}
            or header.get("schema") != "baseline-tmpfs-output-v1"
            or header.get("request_sha256") != request.request_sha256
            or header.get("collector_command_sha256") != command_sha
            or header.get("quiescent") is not True
            or not isinstance(header.get("files"), list)
            or not 1 <= len(header["files"]) <= request.limits.max_output_files
        ):
            raise DockerCommandError("BASELINE_RUN_OUTPUT_ENVELOPE_INVALID")
        expected = {}
        for row in header["files"]:
            if (
                not isinstance(row, dict)
                or set(row) != {"path", "sha256", "size_bytes"}
                or not isinstance(row.get("path"), str)
                or row["path"] in expected
                or not isinstance(row.get("sha256"), str)
                or IDENTITY.fullmatch(row["sha256"]) is None
                or type(row.get("size_bytes")) is not int
                or row["size_bytes"] < 0
            ):
                raise DockerCommandError("BASELINE_RUN_OUTPUT_ENVELOPE_INVALID")
            _parts(row["path"])
            expected[row["path"]] = (row["sha256"], row["size_bytes"])
        if sum(size for _, size in expected.values()) > request.limits.max_output_bytes:
            raise DockerCommandError("BASELINE_RUN_OUTPUT_LIMIT")
        artifacts = await asyncio.to_thread(self._extract, request, job, payload)
        if {
            artifact.path.removeprefix("output/"): (artifact.sha256, artifact.size_bytes)
            for artifact in artifacts
        } != expected:
            raise DockerCommandError("BASELINE_RUN_OUTPUT_CHANGED")
        return artifacts

    def _save(self, request: BaselineRunRequest, receipt: BaselineRunReceipt) -> BaselineRunReceipt:
        job = self._job(request)
        _path(job)
        binding = job / "request.json"
        _path(binding)
        binding_data = _json(binding.read_bytes()) if binding.is_file() else None
        if (
            job.is_dir()
            and binding.is_file()
            and isinstance(binding_data, dict)
            and binding_data.get("request_sha256") == request.request_sha256
        ):
            receipt_bytes = _bytes(asdict(receipt))
            (job / "receipt.json").write_bytes(receipt_bytes)
            (job / "artifact-index.json").write_bytes(
                _bytes(
                    {
                        "request_sha256": request.request_sha256,
                        "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
                        "artifacts": [asdict(item) for item in receipt.artifacts],
                    }
                )
            )
        return receipt

    def _read_private(self, path: Path, limit: int = MAX_JSON) -> bytes:
        _path(path)
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise _fail("BASELINE_RUN_RECOVERY_UNSAFE")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            content = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        _path(path)
        if (
            len(content) > limit
            or _signature(before) != _signature(opened)
            or _signature(opened) != _signature(after)
            or _signature(after) != _signature(path.lstat())
        ):
            raise _fail("BASELINE_RUN_RECOVERY_CHANGED")
        return content

    def _saved_receipt(self, request: BaselineRunRequest, container: str) -> BaselineRunReceipt:
        job = self._job(request)
        _path(job, directory=True)
        binding = _json(self._read_private(job / "request.json"))
        index = _json(self._read_private(job / "artifact-index.json"))
        content = self._read_private(
            job / "receipt.json",
            request.limits.max_log_bytes * 6
            + (request.limits.max_output_files + 1) * 16384
            + 65536,
        )
        if (
            not isinstance(binding, dict)
            or binding.get("request_sha256") != request.request_sha256
            or binding.get("input_manifest_sha256") != run_input_manifest_sha256(request)
            or not isinstance(index, dict)
            or index.get("request_sha256") != request.request_sha256
            or index.get("receipt_sha256") != hashlib.sha256(content).hexdigest()
        ):
            raise _fail("BASELINE_RUN_RECOVERY_SCOPE_CHANGED")
        raw = _json(content)
        if not isinstance(raw, dict):
            raise _fail("BASELINE_RUN_RECOVERY_INVALID")
        values = dict(raw)
        values["job_id"] = uuid.UUID(values["job_id"])
        values["began_at"] = datetime.fromisoformat(values["began_at"])
        values["ended_at"] = datetime.fromisoformat(values["ended_at"])
        values["issues"] = tuple(values["issues"])
        values["artifacts"] = tuple(BaselineRunArtifact(**item) for item in values["artifacts"])
        if values.get("input_seal") is not None:
            values["input_seal"] = BaselineInputSeal(**values["input_seal"])
        receipt = BaselineRunReceipt(**values)
        if (
            receipt.job_id != request.job_id
            or receipt.container_id != container
            or receipt.container_name != run_container_name(request)
            or receipt.image_id != request.image_id
            or receipt.daemon_id != request.daemon_id
            or receipt.command_sha256 != run_command_sha256(request)
            or receipt.input_manifest_sha256 != run_input_manifest_sha256(request)
            or receipt.scientific_qualification != "NOT_GRANTED"
            or receipt.began_at.utcoffset() is None
            or receipt.ended_at.utcoffset() is None
            or receipt.ended_at < receipt.began_at
            or type(receipt.exit_code) not in {int, type(None)}
            or type(receipt.container_stopped) not in {bool, type(None)}
            or type(receipt.input_sealed) is not bool
            or receipt.retained is not True
            or not isinstance(receipt.logs, str)
            or len(receipt.logs.encode()) > request.limits.max_log_bytes
            or receipt.status
            not in {
                "EXITED",
                "CANCELLED",
                "TIMED_OUT",
                "LIMIT_EXCEEDED",
                "QUARANTINED",
                "UNKNOWN",
                "REJECTED",
            }
            or [asdict(item) for item in receipt.artifacts] != index.get("artifacts")
        ):
            raise _fail("BASELINE_RUN_RECOVERY_SCOPE_CHANGED")
        if receipt.input_sealed:
            proof = receipt.input_seal
            if (
                not isinstance(proof, BaselineInputSeal)
                or proof.volume_name != run_volume_name(request)
                or proof.manifest_sha256 != run_input_manifest_sha256(request)
                or proof.verifier_image_id != request.image_id
                or proof.verifier_command_sha256 != run_verifier_command_sha256(request)
                or proof.helper_removed is not True
                or proof.mounted_readonly is not True
                or IDENTITY.fullmatch(proof.helper_container_id) is None
            ):
                raise _fail("BASELINE_RUN_RECOVERY_SEAL_INVALID")
        seen = set()
        total = 0
        count = 0
        snapshots = []
        for artifact in receipt.artifacts:
            _parts(artifact.path)
            if (
                artifact.path in seen
                or type(artifact.size_bytes) is not int
                or artifact.size_bytes < 0
                or IDENTITY.fullmatch(artifact.sha256) is None
            ):
                raise _fail("BASELINE_RUN_RECOVERY_ARTIFACT_INVALID")
            seen.add(artifact.path)
            if artifact.path == "stdout.log":
                if artifact.size_bytes > request.limits.max_log_bytes:
                    raise _fail("BASELINE_RUN_RECOVERY_ARTIFACT_LIMIT")
            elif artifact.path.startswith("output/"):
                count += 1
                total += artifact.size_bytes
            else:
                raise _fail("BASELINE_RUN_RECOVERY_ARTIFACT_INVALID")
            if count > request.limits.max_output_files or total > request.limits.max_output_bytes:
                raise _fail("BASELINE_RUN_RECOVERY_ARTIFACT_LIMIT")
            path = job.joinpath(*_parts(artifact.path))
            _path(path)
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode) or before.st_size != artifact.size_bytes:
                raise _fail("BASELINE_RUN_RECOVERY_ARTIFACT_CHANGED")
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                while chunk := stream.read(65536):
                    size += len(chunk)
                    if size > artifact.size_bytes:
                        raise _fail("BASELINE_RUN_RECOVERY_ARTIFACT_CHANGED")
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
            _path(path)
            if (
                _signature(before) != _signature(opened)
                or _signature(opened) != _signature(after)
                or _signature(after) != _signature(path.lstat())
                or (digest.hexdigest(), size) != (artifact.sha256, artifact.size_bytes)
            ):
                raise _fail("BASELINE_RUN_RECOVERY_ARTIFACT_CHANGED")
            snapshots.append((path, _signature(after)))
        for path, signature in snapshots:
            _path(path)
            if _signature(path.lstat()) != signature:
                raise _fail("BASELINE_RUN_RECOVERY_ARTIFACT_CHANGED")
        return receipt

    async def execute(
        self,
        request: BaselineRunRequest,
        *,
        on_created: CreatedCallback | None = None,
        cancel_requested: CancelRequested | None = None,
    ) -> BaselineRunReceipt:
        began = datetime.now(UTC)
        container = None
        manifest = None
        seal = None
        job = None
        logs = ""
        exit_code = None
        task = None
        retained_artifacts: tuple[BaselineRunArtifact, ...] = ()
        try:
            self._validate(request)
            if not (await self.runtime()).available:
                return self._receipt(
                    request, "REJECTED", issues=("LOCAL_DOCKER_RUNTIME_UNVERIFIED",), began=began
                )
            if cancel_requested and await cancel_requested():
                return self._receipt(
                    request,
                    "CANCELLED",
                    issues=("CANCELLED_BEFORE_CONTAINER",),
                    stopped=True,
                    began=began,
                )
            job, manifest, snapshots = await asyncio.to_thread(self._stage, request)
            seal = await self._volume(request, job, manifest)
            await asyncio.to_thread(self._source_fence, snapshots)
            created = await self._call(
                "container",
                "create",
                "--name=" + self._name(request),
                *self._limits_args(request),
                "--user=65534:65534",
                "--mount=type=volume,source=" + seal.volume_name + ",target=/input,readonly",
                "--tmpfs=/output:" + self._output_tmpfs(request),
                "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=4194304,mode=1777",
                "--env=HOME=/tmp",
                "--env=PYTHONDONTWRITEBYTECODE=1",
                "--env=PYTHONNOUSERSITE=1",
                "--entrypoint=python",
                self.image,
                "-I",
                "-B",
                "-c",
                self._keepalive(request),
            )
            container = created.stdout.decode().strip()
            await self._verify_container(request, container)
            seal = replace(seal, mounted_readonly=True)
            if on_created is not None:
                await on_created(container, self._name(request))
            if cancel_requested and await cancel_requested():
                stopped = await self._stop(request, container)
                return self._save(
                    request,
                    self._receipt(
                        request,
                        "CANCELLED" if stopped else "UNKNOWN",
                        container=container,
                        manifest=manifest,
                        seal=seal,
                        stopped=stopped,
                        issues=("CANCELLED_BEFORE_EXEC",),
                        began=began,
                    ),
                )
            await self._call("container", "start", container)
            raw = await self._verify_container(request, container)
            if raw.get("State", {}).get("Running") is not True:
                raise DockerCommandError("DOCKER_START_UNCONFIRMED")
            config = next(
                item for item in request.inputs if item.asset_id == request.config_asset_id
            )
            task = asyncio.create_task(
                self._call(
                    "container",
                    "exec",
                    "--user=65534:65534",
                    "--env=RESEARCHOS_INPUT_DIR=/input",
                    "--env=RESEARCHOS_OUTPUT_DIR=/output",
                    "--env=RESEARCHOS_CONFIG_FILE=/input/" + config.relative_path,
                    "--env=RESEARCHOS_RANDOM_SEED=" + str(request.random_seed),
                    container,
                    "python",
                    "-I",
                    "-B",
                    "-c",
                    EXEC_PROFILE,
                    *self._entry(request),
                    timeout=request.limits.timeout_seconds + 10,
                    max_bytes=request.limits.max_log_bytes,
                    required=False,
                )
            )
            deadline = time.monotonic() + request.limits.timeout_seconds
            while not task.done():
                if (cancel_requested and await cancel_requested()) or time.monotonic() > deadline:
                    reason: BaselineRunStatus = (
                        "CANCELLED" if time.monotonic() <= deadline else "TIMED_OUT"
                    )
                    stopped = await self._stop(request, container)
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    return self._save(
                        request,
                        self._receipt(
                            request,
                            reason if stopped else "UNKNOWN",
                            container=container,
                            manifest=manifest,
                            seal=seal,
                            stopped=stopped,
                            issues=("EXEC_STOP_REQUESTED",),
                            began=began,
                        ),
                    )
                await asyncio.sleep(0.1)
            completed = task.result()
            exit_code = completed.returncode
            rawlogs = (completed.stdout + b"\n" + completed.stderr)[: request.limits.max_log_bytes]
            logs = (
                rawlogs.decode("utf-8", "replace")
                .encode()[: request.limits.max_log_bytes]
                .decode("utf-8", "ignore")
            )
            (job / "stdout.log").write_bytes(rawlogs)
            log_artifact = BaselineRunArtifact(
                "stdout.log", hashlib.sha256(rawlogs).hexdigest(), len(rawlogs)
            )
            retained_artifacts = (log_artifact,)
            artifacts = await self._collect_tmpfs(request, container, job)
            changed = False
            try:
                await asyncio.to_thread(self._source_fence, snapshots)
            except (DomainError, OSError):
                changed = True
            stopped = await self._stop(request, container)
            status: BaselineRunStatus = (
                "QUARANTINED"
                if changed
                else "EXITED"
                if stopped and 0 <= exit_code <= 124
                else "UNKNOWN"
            )
            return self._save(
                request,
                self._receipt(
                    request,
                    status,
                    container=container,
                    manifest=manifest,
                    seal=seal,
                    stopped=stopped,
                    exit_code=exit_code,
                    logs=logs,
                    artifacts=(log_artifact, *artifacts),
                    issues=("SOURCE_CHANGED_DURING_RUN",)
                    if changed
                    else (() if stopped else ("CONTAINER_STOP_UNCONFIRMED",)),
                    began=began,
                ),
            )
        except (
            DockerCommandError,
            DomainError,
            OSError,
            ValueError,
            tarfile.TarError,
            TypeError,
        ) as error:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            issue = (
                error.code
                if isinstance(error, (DockerCommandError, DomainError))
                else "LOCAL_RUNNER_RESPONSE_OR_IO_INVALID"
            )
            failed_stop = (
                await self._stop(request, container)
                if container and IDENTITY.fullmatch(container)
                else None
            )
            resource_issues: tuple[str, ...] = ()
            if job is not None:
                try:
                    resources = await self._resource_closure(request)
                    resource_issues = self._resource_issues(resources)
                    if container is None and run_container_name(request) in resources:
                        container = resources[run_container_name(request)]["Id"]
                    if failed_stop is not True:
                        failed_stop = self._resources_stopped(resources)
                except (DockerCommandError, DomainError, OSError, ValueError, TypeError):
                    resource_issues = ("JOB_RESOURCE_CLOSURE_UNCONFIRMED",)
            status = (
                "LIMIT_EXCEEDED"
                if failed_stop and issue in {"DOCKER_CLI_OUTPUT_LIMIT", "BASELINE_RUN_OUTPUT_LIMIT"}
                else "REJECTED"
                if job is None
                else "QUARANTINED"
                if failed_stop is True
                and (
                    issue.startswith("BASELINE_RUN_OUTPUT_")
                    or issue == "BASELINE_RUN_NO_OUTPUT_ARTIFACTS"
                )
                else "UNKNOWN"
            )
            failed_receipt = self._receipt(
                request,
                status,
                container=container,
                manifest=manifest,
                seal=seal,
                stopped=failed_stop,
                exit_code=exit_code,
                logs=logs,
                artifacts=retained_artifacts,
                issues=(issue, *resource_issues),
                began=began,
            )
            return self._save(request, failed_receipt) if job is not None else failed_receipt

    async def inspect(self, request: BaselineRunRequest, container_id: str) -> BaselineRunReceipt:
        try:
            self._validate(request)
            if not (await self.runtime()).available:
                raise DockerCommandError("DOCKER_RUNTIME_UNAVAILABLE")
            resources = await self._resource_closure(request)
            main = resources.get(run_container_name(request))
            helper = resources.get(run_helper_container_name(request))
            if container_id != run_container_name(request) and (
                main is None or main["Id"] != container_id
            ):
                raise DockerCommandError("DOCKER_CONTAINER_ID_INVALID")
            stopped = self._resources_stopped(resources)
            if main is None:
                return self._receipt(
                    request,
                    "REJECTED" if stopped else "UNKNOWN",
                    stopped=stopped,
                    issues=("NO_MAIN_EXECUTION_RECEIPT", *self._resource_issues(resources)),
                )
            if stopped and helper is None:
                try:
                    saved = await asyncio.to_thread(self._saved_receipt, request, main["Id"])
                    # Original observed Python result is retained unchanged;
                    # Docker's keepalive ExitCode never substitutes for it.
                    return replace(saved, container_stopped=True)
                except (DomainError, OSError, ValueError, TypeError, KeyError):
                    pass
            return self._receipt(
                request,
                "UNKNOWN",
                container=main["Id"],
                stopped=stopped,
                issues=(
                    "READONLY_LIFECYCLE_RECONCILIATION_NO_REPLAY",
                    "CAPTURED_RESULT_MISSING_OR_UNVERIFIED",
                    *self._resource_issues(resources),
                ),
            )
        except (DockerCommandError, DomainError, ValueError, OSError):
            return self._receipt(
                request,
                "UNKNOWN",
                container=container_id,
                issues=("LIFECYCLE_RECONCILIATION_UNCONFIRMED",),
            )

    async def cancel(self, request: BaselineRunRequest, container_id: str) -> BaselineRunReceipt:
        try:
            self._validate(request)
            if not (await self.runtime()).available:
                raise DockerCommandError("DOCKER_RUNTIME_UNAVAILABLE")
            resources = await self._resource_closure(request)
            main = resources.get(run_container_name(request))
            if container_id != run_container_name(request) and (
                main is None or main["Id"] != container_id
            ):
                raise DockerCommandError("DOCKER_CONTAINER_ID_INVALID")
            for name, raw in resources.items():
                if self._resources_stopped({name: raw}):
                    continue
                identity = raw["Id"]
                if raw.get("State", {}).get("Paused") is True:
                    await self._call("container", "unpause", identity)
                await self._call("container", "stop", "--time=1", identity, timeout=10)
            observed = await self._resource_closure(request)
            stopped = self._resources_stopped(observed)
            return self._receipt(
                request,
                "CANCELLED" if stopped else "UNKNOWN",
                container=main["Id"] if main else None,
                stopped=stopped,
                issues=("EXPLICIT_JOB_RESOURCE_STOP", *self._resource_issues(observed)),
            )
        except (DomainError, DockerCommandError, OSError, ValueError):
            return self._receipt(
                request, "UNKNOWN", container=container_id, issues=("CANCEL_SCOPE_INVALID",)
            )

    async def open_artifact(self, request: BaselineRunRequest, path: str) -> AsyncIterator[bytes]:
        self._validate(request)
        job = self._job(request)
        _path(job, directory=True)
        index_path = job / "artifact-index.json"
        _path(index_path)
        if not index_path.is_file() or index_path.stat().st_size > MAX_JSON:
            raise _fail("BASELINE_RUN_ARTIFACT_SCOPE_CHANGED")
        index = _json(index_path.read_bytes())
        if not isinstance(index, dict) or index.get("request_sha256") != request.request_sha256:
            raise _fail("BASELINE_RUN_ARTIFACT_SCOPE_CHANGED")
        matches = [row for row in index.get("artifacts", []) if row.get("path") == path]
        if len(matches) != 1:
            raise _fail("BASELINE_RUN_ARTIFACT_NOT_RECORDED")
        actual = job.joinpath(*_parts(path))
        _path(actual)
        before = actual.lstat()
        row = matches[0]
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size != row["size_bytes"]
            or before.st_size > request.limits.max_output_bytes + request.limits.max_log_bytes
        ):
            raise _fail("BASELINE_RUN_ARTIFACT_CHANGED")
        digest = hashlib.sha256()
        with actual.open("rb") as stream:
            while chunk := stream.read(65536):
                digest.update(chunk)
                yield chunk
            after = os.fstat(stream.fileno())
        _path(actual)
        if (
            _signature(before) != _signature(after)
            or _signature(after) != _signature(actual.lstat())
            or digest.hexdigest() != row["sha256"]
        ):
            raise _fail("BASELINE_RUN_ARTIFACT_CHANGED")
