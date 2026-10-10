"""Create a portable ResearchOS PostgreSQL and attachment backup.

The archive contains sensitive research data. Keep it in a protected location.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
FORMAT = "researchos-backup"
VERSION = 1
SAFE_CONFIG_KEYS = frozenset(
    {
        "APP_ENV",
        "PDF_ANNOTATIONS_ENABLED",
        "APP_TIMEZONE",
        "WEB_PORT",
        "API_PORT",
        "POSTGRES_DB",
        "STORAGE_PROVIDER",
        "MAX_UPLOAD_MB",
        "SERVER_RESULT_MAX_UPLOAD_MB",
        "SERVER_RESULT_SERVER_ID",
        "ZOTERO_MODE",
        "CODEX_PROVIDER",
        "CODEX_MODEL",
        "CODEX_REASONING_EFFORT",
        "CODEX_TASK_TIMEOUT_SECONDS",
        "CODEX_MAX_TOKENS_PER_TASK",
        "CODEX_BUDGET_MODE",
        "AI_PROVIDER",
        "CODEX_PAPER_TIMEOUT_SECONDS",
        "PAPER_READING_SKILLS_ROOT",
        "ANALYTICAL_WRITER_SKILL_PATH",
        "ANALYTICAL_NOTE_TEMPLATE_PATH",
        "ANALYTICAL_NOTE_ROOT",
        "CANONICAL_PUBLICATION_AUTO_RETRY",
        "SKILL_DISCOVERY_ENABLED",
        "SKILL_DISCOVERY_ROOTS_JSON",
        "RESEARCH_PLANNING_ENABLED",
        "RESEARCH_PLANNING_SKILLS_ROOT",
        "WRITING_ENABLED",
        "WRITING_SKILLS_ROOT",
        "WRITING_IEEE_SKILLS_ROOT",
        "MANUSCRIPT_BUILDS_ENABLED",
        "MANUSCRIPT_TEMPLATES_ROOT",
        "MANUSCRIPT_PRIVATE_TEMPLATES_ROOT",
        "LATEX_DOCKER_EXECUTABLE",
        "LATEX_COMPILER_IMAGE_ID",
        "LATEX_SCRATCH_ROOT",
        "REPOSITORY_ASSETS_ENABLED",
        "PROJECT_SOURCE_WORKSPACES_ENABLED",
        "BASELINE_RUNNER_ENABLED",
        "BASELINE_RUNNER_DOCKER_EXECUTABLE",
        "BASELINE_RUNNER_DOCKER_HOST",
        "BASELINE_RUNNER_IMAGE_ID",
        "BASELINE_RUNNER_DAEMON_ID",
        "BASELINE_RUNNER_ROOT",
        "REPOSITORY_ASSET_MAX_BYTES",
        "REPOSITORY_ASSET_MAX_FILES",
        "GITHUB_GCM_ACCOUNT",
        "PROJECT_ARCHIVE_CATALOG_ENABLED",
        "PROJECT_ARCHIVE_WRITE_ENABLED",
        "CODE_CHANGES_ENABLED",
        "PROJECT_ARCHIVE_WORKSPACES_JSON",
        "PROJECT_PROVISION_ENABLED",
        "PROJECT_PROVISION_MANAGED_ROOT",
        "PROJECT_PROVISION_GITHUB_OWNER",
        "PROJECT_PROVISION_GITHUB_OWNER_ID",
    }
)
CHUNK_SIZE = 1024 * 1024


class BackupError(RuntimeError):
    """A backup operation failed without exposing connection credentials."""


def _local_pg_env(source_env: dict[str, str]) -> tuple[dict[str, str], str]:
    env = source_env.copy()
    url = env.get("DATABASE_URL")
    if url:
        parsed = urlsplit(url)
        if parsed.scheme not in {"postgresql", "postgresql+psycopg", "postgres"}:
            raise BackupError("DATABASE_URL must refer to PostgreSQL")
        dbname = unquote(parsed.path.lstrip("/"))
        if not dbname:
            raise BackupError("DATABASE_URL has no database name")
        if parsed.hostname:
            env["PGHOST"] = parsed.hostname
        if parsed.port:
            env["PGPORT"] = str(parsed.port)
        if parsed.username:
            env["PGUSER"] = unquote(parsed.username)
        if parsed.password:
            env["PGPASSWORD"] = unquote(parsed.password)
        return env, dbname
    local_dbname = env.get("PGDATABASE") or env.get("POSTGRES_DB")
    if not local_dbname:
        raise BackupError("Local mode needs DATABASE_URL or PGDATABASE")
    return env, local_dbname


def _dump_database(mode: str, destination: Path, *, repo: Path = REPO_ROOT) -> str:
    if mode == "compose":
        command = [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "sh",
            "-c",
            'export PGPASSWORD="$POSTGRES_PASSWORD"; exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-privileges',
        ]
        env = os.environ.copy()
        dbname = _read_safe_config(repo).get("POSTGRES_DB", "compose:POSTGRES_DB")
    else:
        env, dbname = _local_pg_env(os.environ.copy())
        command = ["pg_dump", "-Fc", "--no-owner", "--no-privileges", "-d", dbname]
    try:
        with destination.open("wb") as output:
            result = subprocess.run(
                command,
                stdout=output,
                stderr=subprocess.PIPE,
                cwd=repo,
                env=env,
                check=False,
            )
    except FileNotFoundError as exc:
        raise BackupError("Required PostgreSQL/Docker command is unavailable") from exc
    if result.returncode:
        raise BackupError(f"pg_dump failed with exit status {result.returncode}")
    if destination.stat().st_size < 5 or destination.open("rb").read(5) != b"PGDMP":
        raise BackupError("pg_dump did not produce a PostgreSQL custom-format archive")
    return dbname


def _read_safe_config(repo: Path) -> dict[str, str]:
    """Read only an explicit non-secret allowlist; never archive .env itself."""
    config: dict[str, str] = {}
    path = repo / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in SAFE_CONFIG_KEYS:
                config[key] = value.strip().strip('"').strip("'")
    for key in SAFE_CONFIG_KEYS:
        if key in os.environ:
            config[key] = os.environ[key]
    return config


def _attachment_files(root: Path) -> list[Path]:
    if root.is_symlink():
        raise BackupError("Attachment root may not be a symlink")
    if not root.is_dir():
        raise BackupError(f"Attachment directory is missing: {root}")
    files: list[Path] = []
    for parent, dirs, names in os.walk(root, followlinks=False):
        base = Path(parent)
        for name in dirs + names:
            if (base / name).is_symlink():
                raise BackupError("Symlinks in attachment storage are not supported")
        files.extend(base / name for name in names if (base / name).is_file())
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _add_file(
    archive: zipfile.ZipFile, source: Path, archive_name: str
) -> dict[str, str | int]:
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as input_file, archive.open(archive_name, "w") as output:
        while chunk := input_file.read(CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
            output.write(chunk)
    return {"path": archive_name, "bytes": size, "sha256": digest.hexdigest()}


def create_backup(
    output: Path,
    *,
    mode: str = "compose",
    attachments_root: Path | None = None,
    repo: Path = REPO_ROOT,
    allow_missing_attachments: bool = False,
) -> dict[str, object]:
    if mode not in {"compose", "local"}:
        raise BackupError("Mode must be compose or local")
    repo = repo.resolve()
    attachment_path = attachments_root or repo / "data" / "attachments"
    if attachment_path.is_symlink():
        raise BackupError("Attachment root may not be a symlink")
    attachments = attachment_path.resolve()
    output = output.resolve()
    if output.exists():
        raise BackupError("Backup output already exists; choose a new filename")
    if output.is_relative_to(attachments):
        raise BackupError("Backup output cannot be inside attachment storage")
    if not attachments.exists() and allow_missing_attachments:
        files: list[Path] = []
    else:
        files = _attachment_files(attachments)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="researchos-backup-") as temporary:
        db_file = Path(temporary) / "db.dump"
        dbname = _dump_database(mode, db_file, repo=repo)
        config_file = Path(temporary) / "config.json"
        config_file.write_text(
            json.dumps(
                _read_safe_config(repo), ensure_ascii=False, sort_keys=True, indent=2
            ),
            encoding="utf-8",
        )
        temp_archive = Path(temporary) / "archive.zip"
        with zipfile.ZipFile(
            temp_archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True
        ) as archive:
            entries = [_add_file(archive, db_file, "db.dump")]
            entries.append(_add_file(archive, config_file, "config.json"))
            for file in files:
                relative = file.relative_to(attachments).as_posix()
                entries.append(_add_file(archive, file, f"attachments/{relative}"))
            manifest: dict[str, object] = {
                "format": FORMAT,
                "version": VERSION,
                "created_at": datetime.now(UTC).isoformat(),
                "database": {
                    "format": "pg_dump_custom",
                    "mode": mode,
                    "source_name": dbname,
                },
                "attachments_count": len(files),
                "attachments_missing": not attachments.exists(),
                "files": entries,
            }
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
            )
        # Exclusive creation means concurrent backup jobs cannot overwrite one another.
        created_output = False
        try:
            with output.open("xb") as destination, temp_archive.open("rb") as source:
                created_output = True
                shutil.copyfileobj(source, destination, CHUNK_SIZE)
        except BaseException:
            if created_output:
                output.unlink(missing_ok=True)
            raise
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", required=True, type=Path, help="New .zip archive path"
    )
    parser.add_argument("--mode", choices=["compose", "local"], default="compose")
    parser.add_argument("--attachments-root", type=Path)
    parser.add_argument("--allow-missing-attachments", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = create_backup(
            args.output,
            mode=args.mode,
            attachments_root=args.attachments_root,
            allow_missing_attachments=args.allow_missing_attachments,
        )
    except (BackupError, OSError) as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1
    print(f"Created {args.output} ({manifest['attachments_count']} attachments)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
