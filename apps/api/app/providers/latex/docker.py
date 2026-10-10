"""Fixed non-root Docker document compilation; no host compiler fallback."""

import base64
import json
import os
import re
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal

from app.domain.latex_compilation import (
    ENGINE,
    ISOLATION_CONTRACT,
    MAX_LOG_BYTES,
    MAX_PDF_BYTES,
    LatexCompilerCapabilities,
    LatexCompileRequest,
    LatexCompileResult,
    sha256,
    validate_request,
)

ENTRYPOINT = ["/usr/local/bin/python", "-I", "-B", "/opt/researchos/compile_document.py"]
CONTEXT = "desktop-linux"


def _plain_path(path: Path) -> None:
    for item in (path, *path.parents):
        value = item.lstat()
        if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
            raise ValueError("Compiler staging must not contain links or reparse points")


def _read_plain(path: Path, bound: int) -> bytes:
    _plain_path(path)
    value = path.stat()
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or value.st_size > bound:
        raise ValueError("Compiler output is not a bounded plain file")
    with path.open("rb") as stream:
        result = stream.read(bound + 1)
    if len(result) > bound:
        raise ValueError("Compiler output exceeded its byte bound")
    return result


class DockerLatexCompilationProvider:
    provider_key = "docker_latex"

    def __init__(self, *, docker_executable: Path, image_id: str, scratch_root: Path):
        self.docker = docker_executable
        self.image_id = image_id
        self.scratch = scratch_root

    def _call(
        self, arguments: list[str], *, timeout: float = 10
    ) -> subprocess.CompletedProcess[bytes]:
        # No shell, user environment, engine or command is accepted from a compile request.
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper()
            in {
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "PATH",
                "LOCALAPPDATA",
                "APPDATA",
                "USERPROFILE",
            }
        }
        return subprocess.run(
            [str(self.docker), "--context", CONTEXT, *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=environment,
            shell=False,
        )

    def probe(self) -> LatexCompilerCapabilities:
        try:
            if (
                not self.docker.is_absolute()
                or not self.docker.is_file()
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image_id)
            ):
                raise ValueError("Configure a local Docker executable and immutable image ID")
            endpoint = self._call(
                ["context", "inspect", CONTEXT, "--format", "{{json .Endpoints.docker.Host}}"]
            )
            if (
                endpoint.returncode
                or json.loads(endpoint.stdout) != "npipe:////./pipe/dockerDesktopLinuxEngine"
            ):
                raise ValueError(
                    "The compiler requires the verified local Docker Desktop Linux endpoint"
                )
            engine = self._call(["version", "--format", "{{json .Server}}"])
            if engine.returncode or json.loads(engine.stdout).get("Os") != "linux":
                raise ValueError("The local Linux Docker daemon is unavailable")
            image = self._call(["image", "inspect", self.image_id])
            values = json.loads(image.stdout) if image.returncode == 0 else []
            if len(values) != 1:
                raise ValueError(
                    "The pinned compiler image is unavailable; no implicit pull is permitted"
                )
            value = values[0]
            config = value["Config"]
            labels = config.get("Labels", {})
            if (
                value["Id"] != self.image_id
                or config.get("User") != "42424:42424"
                or config.get("Entrypoint") != ENTRYPOINT
                or labels.get("org.researchos.latex.contract") != ISOLATION_CONTRACT
                or labels.get("org.researchos.latex.engine") != ENGINE
                or labels.get("org.researchos.latex.font") != "Noto Serif CJK SC"
            ):
                raise ValueError(
                    "Compiler image configuration differs from the fixed document contract"
                )
            return LatexCompilerCapabilities(
                True, "PINNED_LOCAL_IMAGE_AVAILABLE_NOT_A_BUILD_RECEIPT", self.image_id
            )
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
            return LatexCompilerCapabilities(
                False,
                str(error),
                self.image_id if re.fullmatch(r"sha256:[0-9a-f]{64}", self.image_id) else None,
            )

    def _create_arguments(self, source: Path, output: Path, label: str) -> list[str]:
        for path in (source, output):
            if "," in str(path):
                raise ValueError("Docker bind source cannot contain a comma")
        return [
            "create",
            "--pull=never",
            "--name",
            label,
            "--label",
            "org.researchos.document-job=" + label,
            "--network=none",
            "--read-only",
            "--user=42424:42424",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--cpus=1",
            "--memory=512m",
            "--memory-swap=512m",
            "--pids-limit=32",
            "--ulimit",
            "fsize=33554432:33554432",
            "--ulimit",
            "nofile=64:64",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=33554432",
            "--mount",
            f"type=bind,src={source},dst=/input,readonly",
            "--tmpfs",
            "/out:rw,noexec,nosuid,nodev,size=33554432,mode=1777",
            "--log-driver=none",
            "--ipc=none",
            "--workdir=/input",
            self.image_id,
        ]

    def _verify_container(
        self, identity: str, source: Path, output: Path, label: str
    ) -> dict[str, object]:
        inspected = self._call(["inspect", identity])
        if inspected.returncode:
            raise ValueError("Created compiler container cannot be inspected")
        value: dict[str, Any] = json.loads(inspected.stdout)[0]
        host = value["HostConfig"]
        config = value["Config"]
        mounts = value["Mounts"]
        bindings = {entry["Destination"]: entry for entry in mounts}
        paths = {"/input": source}
        if (
            value["Id"] != identity
            or value["Image"] != self.image_id
            or config.get("User") != "42424:42424"
            or config.get("Entrypoint") != ENTRYPOINT
            or config.get("Labels", {}).get("org.researchos.document-job") != label
            or host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True
            or host.get("Privileged") is not False
            or host.get("CapDrop") != ["ALL"]
            or "no-new-privileges:true" not in host.get("SecurityOpt", [])
            or host.get("Memory") != 512 * 1024 * 1024
            or host.get("MemorySwap") != 512 * 1024 * 1024
            or host.get("NanoCpus") != 1_000_000_000
            or host.get("PidsLimit") != 32
            or set(bindings) != set(paths)
            or any(bindings[key].get("Type") != "bind" for key in paths)
            or bindings["/input"].get("RW") is not False
            or host.get("Tmpfs")
            != {
                "/tmp": "rw,noexec,nosuid,nodev,size=33554432",
                "/out": "rw,noexec,nosuid,nodev,size=33554432,mode=1777",
            }
        ):
            raise ValueError("Created container does not prove the required isolation")
        # Docker Desktop normalizes Windows mounts to its internal host path; bind declarations
        # retain the actual requested paths and are checked alongside effective mount flags.
        declarations = host.get("Mounts", [])
        if len(declarations) != 1 or any(
            not any(
                item.get("Target") == key
                and os.path.normcase(item.get("Source", "")) == os.path.normcase(str(path))
                and bool(item.get("ReadOnly", False)) == (key == "/input")
                for item in declarations
            )
            for key, path in paths.items()
        ):
            raise ValueError("Created container mount source differs")
        return {
            "phase": "CONTAINER_ISOLATION_VERIFIED",
            "container_id": identity,
            "image_id": self.image_id,
            "network": "none",
            "nonroot_user": "42424:42424",
            "readonly_root": True,
            "input_readonly": True,
            "mounts": ["FROZEN_INPUT_ONLY"],
            "output_tmpfs_bytes": 33554432,
            "shell_escape": False,
            "cpus": 1,
            "memory_bytes": 512 * 1024 * 1024,
            "pids_limit": 32,
        }

    def compile(self, request: LatexCompileRequest) -> LatexCompileResult:
        validate_request(request)
        capability = self.probe()
        if not capability.available:
            log = capability.reason.encode("utf-8")[:MAX_LOG_BYTES]
            return LatexCompileResult(
                "UNAVAILABLE",
                request.source_sha256,
                capability.image_id,
                None,
                None,
                log,
                sha256(log),
                None,
                (),
            )
        identity = None
        observations: list[dict[str, object]] = []
        log = b""
        code = None
        status: Literal["READY", "FAILED", "UNAVAILABLE", "TIMED_OUT", "NEEDS_ATTENTION"] = (
            "NEEDS_ATTENTION"
        )
        pdf = None
        try:
            _plain_path(self.scratch)
            with tempfile.TemporaryDirectory(
                prefix="latex-document-", dir=self.scratch
            ) as temporary:
                root = Path(temporary)
                if not root.resolve().is_relative_to(self.scratch.resolve()):
                    raise ValueError("Compiler staging escaped its verified scratch root")
                source, output = root / "input", root / "output"
                source.mkdir()
                output.mkdir()
                for item in request.files:
                    target = source / item.path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream:
                        stream.write(item.content)
                label = "researchos-document-" + uuid.uuid4().hex
                made = self._call(self._create_arguments(source, output, label))
                if made.returncode:
                    raise ValueError("Docker compiler container was not created")
                identity = made.stdout.decode("ascii").strip()
                if not re.fullmatch(r"[0-9a-f]{64}", identity):
                    identity = None
                    raise ValueError("Docker did not return an authoritative container ID")
                try:
                    observations.append(self._verify_container(identity, source, output, label))
                    started = self._call(["start", "--attach", identity], timeout=60)
                    code = started.returncode
                    inspected = self._call(["inspect", identity, "--format", "{{json .State}}"])
                    state = json.loads(inspected.stdout) if not inspected.returncode else {}
                    observations.append(
                        {
                            "phase": "CONTAINER_TERMINAL_STATE",
                            "running": bool(state.get("Running", True)),
                            "exit_code": state.get("ExitCode"),
                            "oom_killed": bool(state.get("OOMKilled", False)),
                        }
                    )
                    if state.get("Running", True):
                        raise ValueError("Compiler terminal state is unknown")
                    code = state.get("ExitCode")
                    if len(started.stdout) > (MAX_LOG_BYTES + MAX_PDF_BYTES) * 4 // 3 + 8192:
                        raise ValueError("Compiler output envelope exceeds bound")
                    receipt = json.loads(started.stdout)
                    log = base64.b64decode(receipt.get("log_base64", ""), validate=True)
                    if len(log) > MAX_LOG_BYTES:
                        raise ValueError("Compiler log exceeds bound")
                    if (
                        receipt.get("engine") != ENGINE
                        or receipt.get("no_shell_escape") is not True
                        or receipt.get("exit_code") != code
                    ):
                        raise ValueError(
                            "Compiler entrypoint receipt differs from actual container exit"
                        )
                    if code == 0:
                        pdf = base64.b64decode(receipt.get("pdf_base64", ""), validate=True)
                        if len(pdf) > MAX_PDF_BYTES:
                            raise ValueError("Compiler PDF exceeds bound")
                        if not pdf.startswith(b"%PDF-") or b"%%EOF" not in pdf[-1024:]:
                            raise ValueError("Compiler output is not a complete PDF")
                        status = "READY"
                    else:
                        status = "TIMED_OUT" if code == 124 else "FAILED"
                finally:
                    removed = self._call(["rm", "--force", identity])
                    observations.append(
                        {"phase": "CONTAINER_REMOVAL", "confirmed": removed.returncode == 0}
                    )
                    if removed.returncode != 0:
                        raise ValueError("Compiler container removal could not be confirmed")
                    identity = None
        except subprocess.TimeoutExpired:
            status = "TIMED_OUT"
            log += b"\nCompiler observation timed out; no PDF success is claimed."
        except (OSError, ValueError, KeyError, TypeError) as error:
            log += ("\nCompiler failed closed: " + str(error)).encode("utf-8", errors="replace")
            status = "NEEDS_ATTENTION"
            pdf = None
        finally:
            if identity is not None:
                try:
                    self._call(["rm", "--force", identity])
                except (OSError, subprocess.TimeoutExpired):
                    observations.append({"phase": "CONTAINER_REMOVAL", "confirmed": False})
        log = log[:MAX_LOG_BYTES]
        if status != "READY":
            pdf = None
        return LatexCompileResult(
            status,
            request.source_sha256,
            self.image_id,
            pdf,
            sha256(pdf) if pdf is not None else None,
            log,
            sha256(log),
            code,
            tuple(observations),
        )
