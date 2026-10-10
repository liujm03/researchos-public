"""Bounded local runner receipts; execution never grants scientific qualification."""

import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal, Protocol

from app.domain.baselines import BaselineProbeRequest
from app.domain.project_sources import ProjectSourceFile, ProjectSourceScope

BaselineRunStatus = Literal[
    "EXITED", "CANCELLED", "TIMED_OUT", "LIMIT_EXCEEDED", "QUARANTINED", "UNKNOWN", "REJECTED"
]
PYTHON_EXEC_PROFILE_V1 = "import os,random,runpy,sys;random.seed(int(os.environ['RESEARCHOS_RANDOM_SEED']));os.chdir(sys.argv[2]);sys.path.insert(0,sys.argv[2]);p=sys.argv[1];sys.argv=[p];runpy.run_path(p,run_name='__main__')"
RUN_INPUT_MARKER = ".researchos-input-manifest.json"

# Runs inside the existing bounded container after the user command exits.
# Refuses collection while any other non-zombie process could still write.
RUN_OUTPUT_COLLECTOR_V1 = r"""import hashlib,json,os,pathlib,stat,sys,tarfile,time
class CollectionFailure(Exception):
 def __init__(self,code): self.code=code
def quiescent():
 me=os.getpid()
 for name in os.listdir('/proc'):
  if not name.isdigit() or int(name) in (1,me): continue
  try:
   text=(pathlib.Path('/proc')/name/'status').read_text()
  except FileNotFoundError: continue
  state=next((line.split()[1] for line in text.splitlines() if line.startswith('State:')),None)
  if state!='Z': raise CollectionFailure('BASELINE_RUN_OUTPUT_NOT_QUIESCENT')
def signature(info):
 return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_mode)
def walk_error(error):
 raise CollectionFailure('BASELINE_RUN_OUTPUT_COLLECTION_UNAVAILABLE')
def collect(root,request_sha,command_sha,max_files,max_bytes,sink):
 quiescent();time.sleep(0.02);quiescent()
 files=[];seen=set();total=0;nodes=0
 for directory,folders,names in os.walk(root,followlinks=False,onerror=walk_error):
  for name in folders+names:
   path=pathlib.Path(directory)/name;info=path.lstat();nodes+=1
   if nodes>max_files+32 or stat.S_ISLNK(info.st_mode): raise CollectionFailure('BASELINE_RUN_OUTPUT_UNSAFE')
   if path.is_dir(): continue
   if not stat.S_ISREG(info.st_mode): raise CollectionFailure('BASELINE_RUN_OUTPUT_UNSAFE')
   relative=path.relative_to(root).as_posix()
   if relative in seen: raise CollectionFailure('BASELINE_RUN_OUTPUT_UNSAFE')
   seen.add(relative);total+=info.st_size
   if len(files)>=max_files or total>max_bytes: raise CollectionFailure('BASELINE_RUN_OUTPUT_LIMIT')
   h=hashlib.sha256();size=0
   with path.open('rb') as stream:
    opened=os.fstat(stream.fileno())
    if signature(opened)!=signature(info): raise CollectionFailure('BASELINE_RUN_OUTPUT_CHANGED')
    while True:
     chunk=stream.read(65536)
     if not chunk: break
     size+=len(chunk)
     if size>info.st_size: raise CollectionFailure('BASELINE_RUN_OUTPUT_CHANGED')
     h.update(chunk)
    after=os.fstat(stream.fileno())
   if signature(opened)!=signature(after) or signature(after)!=signature(path.lstat()) or size!=info.st_size: raise CollectionFailure('BASELINE_RUN_OUTPUT_CHANGED')
   files.append((path,relative,h.hexdigest(),size,signature(after)))
 if not files: raise CollectionFailure('BASELINE_RUN_NO_OUTPUT_ARTIFACTS')
 quiescent()
 header={'schema':'baseline-tmpfs-output-v1','request_sha256':request_sha,'collector_command_sha256':command_sha,'quiescent':True,'files':[{'path':r,'sha256':h,'size_bytes':s} for _,r,h,s,_ in files]}
 sink.write(json.dumps(header,sort_keys=True,separators=(',',':')).encode()+b'\n');sink.flush()
 with tarfile.open(fileobj=sink,mode='w|',format=tarfile.USTAR_FORMAT) as archive:
  for path,relative,digest,size,expected in files:
   quiescent()
   if signature(path.lstat())!=expected: raise CollectionFailure('BASELINE_RUN_OUTPUT_CHANGED')
   info=tarfile.TarInfo(relative);info.size=size;info.mode=0o444
   with path.open('rb') as stream:
    if signature(os.fstat(stream.fileno()))!=expected: raise CollectionFailure('BASELINE_RUN_OUTPUT_CHANGED')
    archive.addfile(info,stream)
    if signature(os.fstat(stream.fileno()))!=expected: raise CollectionFailure('BASELINE_RUN_OUTPUT_CHANGED')
   if signature(path.lstat())!=expected: raise CollectionFailure('BASELINE_RUN_OUTPUT_CHANGED')
 quiescent()
 for path,relative,digest,size,expected in files:
  if signature(path.lstat())!=expected: raise CollectionFailure('BASELINE_RUN_OUTPUT_CHANGED')
 sink.flush()
def main():
 try:
  collect(pathlib.Path('/output'),sys.argv[1],sys.argv[2],int(sys.argv[3]),int(sys.argv[4]),sys.stdout.buffer)
 except CollectionFailure as error:
  sys.stderr.write(json.dumps({'schema':'baseline-collector-error-v1','request_sha256':sys.argv[1],'code':error.code})+'\n');sys.exit(65)
 except Exception:
  sys.stderr.write(json.dumps({'schema':'baseline-collector-error-v1','request_sha256':sys.argv[1],'code':'BASELINE_RUN_OUTPUT_COLLECTION_UNAVAILABLE'})+'\n');sys.exit(66)
if __name__=='__main__': main()
"""


@dataclass(frozen=True)
class BaselineRunLimits:
    timeout_seconds: int = 120
    cpu_millicores: int = 1000
    memory_bytes: int = 512 * 1024 * 1024
    pids: int = 32
    max_input_bytes: int = 256 * 1024 * 1024
    max_input_files: int = 1000
    max_log_bytes: int = 1024 * 1024
    max_output_bytes: int = 32 * 1024 * 1024
    max_output_files: int = 100


@dataclass(frozen=True)
class BaselineRunInput:
    asset_id: uuid.UUID
    role: str
    source_scope: ProjectSourceScope
    source_file: ProjectSourceFile
    relative_path: str
    dataset_split: Literal["TRAIN", "VALIDATION"] | None = None
    dataset_version_id: uuid.UUID | None = None
    sample_id: str | None = None
    group_id: str | None = None
    projected_content: bytes | None = None


@dataclass(frozen=True)
class BaselineRunProjection:
    inputs: tuple[BaselineRunInput, ...]
    sha256: str
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class BaselineRunRequest:
    job_id: uuid.UUID
    owner_id: uuid.UUID
    project_id: uuid.UUID
    version_id: uuid.UUID
    version_sha256: str
    request_sha256: str
    grant_sha256: str
    image_id: str
    daemon_id: str
    entry_asset_id: uuid.UUID
    inputs: tuple[BaselineRunInput, ...]
    limits: BaselineRunLimits
    profile: Literal["PYTHON_SCRIPT_V1"] = "PYTHON_SCRIPT_V1"
    config_asset_id: uuid.UUID | None = None
    random_seed: int = 0


@dataclass(frozen=True)
class BaselineRuntimeEvidence:
    available: bool
    docker_host: str
    daemon_id: str | None
    image_id: str | None
    issues: tuple[str, ...]
    checked_at: datetime


@dataclass(frozen=True)
class BaselineRunArtifact:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class BaselineInputSeal:
    volume_name: str
    manifest_sha256: str
    verifier_image_id: str
    verifier_command_sha256: str
    helper_container_id: str
    helper_removed: bool
    mounted_readonly: bool


@dataclass(frozen=True)
class BaselineRunReceipt:
    job_id: uuid.UUID
    status: BaselineRunStatus
    container_id: str | None
    container_name: str
    image_id: str
    daemon_id: str
    command_sha256: str
    input_manifest_sha256: str | None
    exit_code: int | None
    logs: str
    artifacts: tuple[BaselineRunArtifact, ...]
    began_at: datetime
    ended_at: datetime
    issues: tuple[str, ...]
    retained: bool = True
    scientific_qualification: Literal["NOT_GRANTED"] = "NOT_GRANTED"
    input_sealed: bool = False
    container_stopped: bool | None = None
    input_seal: BaselineInputSeal | None = None


CreatedCallback = Callable[[str, str], Awaitable[None]]
CancelRequested = Callable[[], Awaitable[bool]]


class BaselineRunProvider(Protocol):
    async def runtime(self) -> BaselineRuntimeEvidence: ...

    async def project_inputs(self, request: BaselineProbeRequest) -> BaselineRunProjection: ...

    async def execute(
        self,
        request: BaselineRunRequest,
        *,
        on_created: CreatedCallback | None = None,
        cancel_requested: CancelRequested | None = None,
    ) -> BaselineRunReceipt: ...

    async def cancel(
        self, request: BaselineRunRequest, container_id: str
    ) -> BaselineRunReceipt: ...

    async def inspect(
        self, request: BaselineRunRequest, container_id: str
    ) -> BaselineRunReceipt: ...

    def open_artifact(self, request: BaselineRunRequest, path: str) -> "AsyncIterator[bytes]": ...


def run_request_sha256(request: BaselineRunRequest) -> str:
    """Canonical transport scope; generated bytes represented by exact hash/size."""

    def default(value: object) -> object:
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, bytes):
            return {"sha256": hashlib.sha256(value).hexdigest(), "size_bytes": len(value)}
        raise TypeError("Unsupported runner scope value")

    value = asdict(request)
    value.pop("request_sha256")
    return hashlib.sha256(
        json.dumps(
            {"schema": "baseline-python-run-v1", "request": value},
            default=default,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def run_projection_sha256(inputs: tuple[BaselineRunInput, ...]) -> str:
    values = [
        {
            **asdict(item),
            "projected_content": None
            if item.projected_content is None
            else hashlib.sha256(item.projected_content).hexdigest(),
        }
        for item in inputs
    ]
    return hashlib.sha256(
        json.dumps(
            {"schema": "baseline-input-projection-v1", "inputs": values},
            default=lambda value: (
                str(value) if isinstance(value, uuid.UUID) else (_ for _ in ()).throw(TypeError())
            ),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def run_input_manifest_bytes(request: BaselineRunRequest) -> bytes:
    files = [
        {
            "path": item.relative_path,
            "sha256": item.source_file.sha256
            if item.projected_content is None
            else hashlib.sha256(item.projected_content).hexdigest(),
            "size_bytes": item.source_file.size_bytes
            if item.projected_content is None
            else len(item.projected_content),
            "role": item.role,
            "dataset_split": item.dataset_split,
        }
        for item in request.inputs
    ]
    value = {
        "schema": "baseline-run-inputs-v1",
        "job_id": str(request.job_id),
        "owner_id": str(request.owner_id),
        "project_id": str(request.project_id),
        "request_sha256": request.request_sha256,
        "files": files,
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def run_input_manifest_sha256(request: BaselineRunRequest) -> str:
    return hashlib.sha256(run_input_manifest_bytes(request)).hexdigest()


def run_command_sha256(request: BaselineRunRequest) -> str:
    entry = next((item for item in request.inputs if item.asset_id == request.entry_asset_id), None)
    config = next(
        (item for item in request.inputs if item.asset_id == request.config_asset_id), None
    )
    if entry is None or config is None:
        value: object = ["NOT_EXECUTED", request.profile, str(request.entry_asset_id)]
    else:
        path = "/input/" + entry.relative_path
        directory = path.rsplit("/", 1)[0]
        value = {
            "argv": ["python", "-I", "-B", "-c", PYTHON_EXEC_PROFILE_V1, path, directory],
            "environment": {
                "RESEARCHOS_INPUT_DIR": "/input",
                "RESEARCHOS_OUTPUT_DIR": "/output",
                "RESEARCHOS_CONFIG_FILE": "/input/" + config.relative_path,
                "RESEARCHOS_RANDOM_SEED": str(request.random_seed),
            },
        }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


RUN_INPUT_VERIFIER_V1 = "import hashlib,json,os,pathlib,sys\nr=pathlib.Path('/input');m=r/'.researchos-input-manifest.json';b=m.read_bytes()\nassert hashlib.sha256(b).hexdigest()==sys.argv[1]\nj=json.loads(b);expected={v['path']:v for v in j['files']}\nassert len(expected)==len(j['files'])\nfound=set()\nfor d,dirs,files in os.walk(r,followlinks=False):\n for n in dirs+files: assert not (pathlib.Path(d)/n).is_symlink()\n for n in files:\n  p=pathlib.Path(d)/n;q=p.relative_to(r).as_posix()\n  if q==m.name: continue\n  assert q in expected\n  h=hashlib.sha256();s=0\n  with p.open('rb') as f:\n   while True:\n    z=f.read(65536)\n    if not z: break\n    h.update(z);s+=len(z)\n  assert (h.hexdigest(),s)==(expected[q]['sha256'],expected[q]['size_bytes']);found.add(q)\nassert found==set(expected)\nprint(json.dumps({'manifest_sha256':sys.argv[1],'verified_files':len(found)},sort_keys=True))\n"


def run_container_name(request: BaselineRunRequest) -> str:
    return "researchos-run-" + request.job_id.hex


def run_volume_name(request: BaselineRunRequest) -> str:
    return "researchos-input-" + request.job_id.hex


def run_helper_container_name(request: BaselineRunRequest) -> str:
    return run_container_name(request) + "-input-helper"


def run_verifier_command_sha256(request: BaselineRunRequest) -> str:
    command = [
        "python",
        "-I",
        "-B",
        "-c",
        RUN_INPUT_VERIFIER_V1,
        run_input_manifest_sha256(request),
    ]
    return hashlib.sha256(
        json.dumps(command, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def run_collector_command_sha256(request: BaselineRunRequest) -> str:
    # The self hash is passed separately as an envelope identifier.
    command = [
        "python",
        "-I",
        "-B",
        "-c",
        RUN_OUTPUT_COLLECTOR_V1,
        request.request_sha256,
        str(request.limits.max_output_files),
        str(request.limits.max_output_bytes),
    ]
    return hashlib.sha256(
        json.dumps(command, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
