"""Verify or restore a ResearchOS backup into a NEW PostgreSQL database.

This command never drops or overwrites an existing database or attachment directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from backup import (
    CHUNK_SIZE,
    FORMAT,
    REPO_ROOT,
    SAFE_CONFIG_KEYS,
    VERSION,
    BackupError,
    _local_pg_env,
)

DB_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _safe_archive_name(name: str) -> bool:
    if name in {"db.dump", "config.json", "manifest.json"}:
        return True
    if not name.startswith("attachments/") or "\\" in name:
        return False
    parts = name.split("/")[1:]
    for part in parts:
        if not part or part in {".", ".."} or part.endswith((".", " ")):
            return False
        if any(ord(character) < 32 or character in '<>:"\\|?*' for character in part):
            return False
        if part.split(".", 1)[0].upper() in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }:
            return False
    return bool(parts)


def verify_archive(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BackupError("Backup archive does not exist")
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or "manifest.json" not in names:
                raise BackupError("Archive has duplicate entries or no manifest")
            if any(not _safe_archive_name(name) for name in names):
                raise BackupError("Archive contains an unsafe path")
            if any(
                info.compress_type != zipfile.ZIP_STORED for info in archive.infolist()
            ):
                raise BackupError("Archive contains unsupported compression")
            if archive.getinfo("manifest.json").file_size > 8 * CHUNK_SIZE:
                raise BackupError("Manifest exceeds size limit")
            manifest = json.loads(archive.read("manifest.json"))
            if (
                not isinstance(manifest, dict)
                or manifest.get("format") != FORMAT
                or manifest.get("version") != VERSION
            ):
                raise BackupError("Unsupported backup format/version")
            metadata = manifest.get("database")
            if (
                not isinstance(metadata, dict)
                or metadata.get("format") != "pg_dump_custom"
            ):
                raise BackupError(
                    "Archive does not contain a supported PostgreSQL dump"
                )
            files = manifest.get("files")
            if not isinstance(files, list):
                raise BackupError("Manifest file list is invalid")
            listed: set[str] = set()
            for entry in files:
                if not isinstance(entry, dict):
                    raise BackupError("Manifest file entry is invalid")
                name = entry.get("path")
                size = entry.get("bytes")
                digest = entry.get("sha256")
                if (
                    not isinstance(name, str)
                    or not _safe_archive_name(name)
                    or name == "manifest.json"
                ):
                    raise BackupError("Manifest file path is invalid")
                if (
                    name in listed
                    or type(size) is not int
                    or size < 0
                    or not isinstance(digest, str)
                    or not SHA256.fullmatch(digest)
                ):
                    raise BackupError("Manifest file metadata is invalid")
                listed.add(name)
                info = archive.getinfo(name)
                if info.file_size != size:
                    raise BackupError(f"Size mismatch: {name}")
                actual = hashlib.sha256()
                with archive.open(name) as source:
                    while chunk := source.read(CHUNK_SIZE):
                        actual.update(chunk)
                if actual.hexdigest() != digest:
                    raise BackupError(f"SHA-256 mismatch: {name}")
            if listed != set(names) - {"manifest.json"} or not {
                "db.dump",
                "config.json",
            }.issubset(listed):
                raise BackupError("Archive and manifest file lists differ")
            if manifest.get("attachments_count") != len(
                [name for name in listed if name.startswith("attachments/")]
            ):
                raise BackupError("Attachment count does not match manifest")
            if archive.open("db.dump").read(5) != b"PGDMP":
                raise BackupError(
                    "Database file is not a PostgreSQL custom-format dump"
                )
            if archive.getinfo("config.json").file_size > CHUNK_SIZE:
                raise BackupError("Configuration exceeds size limit")
            config = json.loads(archive.read("config.json"))
            if not isinstance(config, dict) or any(
                key not in SAFE_CONFIG_KEYS or not isinstance(value, str)
                for key, value in config.items()
            ):
                raise BackupError("Configuration contains unsupported keys or values")
            return manifest
    except (
        zipfile.BadZipFile,
        KeyError,
        OSError,
        ValueError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        raise BackupError("Archive is unreadable or malformed") from exc


def _command(
    mode: str, action: str, target: str | None = None
) -> tuple[list[str], dict[str, str]]:
    if mode == "compose":
        scripts = {
            "list": 'export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -U "$POSTGRES_USER" -d postgres -At -c "SELECT datname FROM pg_database"',
            "create": 'export PGPASSWORD="$POSTGRES_PASSWORD"; exec createdb -U "$POSTGRES_USER" "$1"',
            "restore": 'export PGPASSWORD="$POSTGRES_PASSWORD"; exec pg_restore -U "$POSTGRES_USER" -d "$1" --no-owner --no-privileges --exit-on-error',
            "inspect": "exec pg_restore --list",
        }
        command = [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "sh",
            "-c",
            scripts[action],
        ]
        if action in {"create", "restore"}:
            command += ["sh", target or ""]
        return command, os.environ.copy()
    env, _ = _local_pg_env(os.environ.copy())
    commands = {
        "list": [
            "psql",
            "-d",
            "postgres",
            "-At",
            "-c",
            "SELECT datname FROM pg_database",
        ],
        "create": ["createdb", "--maintenance-db", "postgres", target or ""],
        "restore": [
            "pg_restore",
            "-d",
            target or "",
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
        ],
        "inspect": ["pg_restore", "--list"],
    }
    return commands[action], env


def _run_database(
    mode: str,
    action: str,
    target: str | None = None,
    *,
    stdin: Any = None,
    repo: Path = REPO_ROOT,
) -> str:
    command, env = _command(mode, action, target)
    try:
        result = subprocess.run(
            command, stdin=stdin, capture_output=True, cwd=repo, env=env, check=False
        )
    except FileNotFoundError as exc:
        raise BackupError("Required PostgreSQL/Docker command is unavailable") from exc
    if result.returncode:
        raise BackupError(
            f"Database {action} failed with exit status {result.returncode}"
        )
    return result.stdout.decode("utf-8", errors="replace")


def _copy_verified_member(
    source: zipfile.ZipFile, name: str, destination: Path, expected: dict[str, Any]
) -> None:
    digest = hashlib.sha256()
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open(name) as input_file, destination.open("xb") as output:
        while chunk := input_file.read(CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
            output.write(chunk)
    if size != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
        raise BackupError(f"Archive changed during restore: {name}")


def preflight_target(
    mode: str,
    target_db: str,
    attachments_target: Path,
    config_target: Path,
    *,
    repo: Path = REPO_ROOT,
) -> None:
    if not DB_NAME.fullmatch(target_db):
        raise BackupError(
            "Target database must be a simple PostgreSQL identifier of at most 63 bytes"
        )
    if attachments_target.exists() or attachments_target.is_symlink():
        raise BackupError(
            "Target attachment path already exists; it will not be overwritten"
        )
    if config_target.exists() or config_target.is_symlink():
        raise BackupError(
            "Target config path already exists; it will not be overwritten"
        )
    databases = set(_run_database(mode, "list", repo=repo).splitlines())
    if target_db in databases:
        raise BackupError(
            "Target database already exists; restore requires a new database"
        )


def restore_backup(
    archive_path: Path,
    *,
    mode: str,
    target_db: str,
    attachments_target: Path,
    config_target: Path,
    confirm_target: str | None = None,
    check_only: bool = False,
    repo: Path = REPO_ROOT,
) -> dict[str, Any]:
    if mode not in {"compose", "local"}:
        raise BackupError("Mode must be compose or local")
    manifest = verify_archive(archive_path)
    attachments_target = attachments_target.absolute()
    config_target = config_target.absolute()
    if config_target.is_relative_to(
        attachments_target
    ) or attachments_target.is_relative_to(config_target):
        raise BackupError("Config output must be separate from attachment storage")
    if not DB_NAME.fullmatch(target_db):
        raise BackupError(
            "Target database must be a simple PostgreSQL identifier of at most 63 bytes"
        )
    if attachments_target.exists() or attachments_target.is_symlink():
        raise BackupError(
            "Target attachment path already exists; it will not be overwritten"
        )
    if config_target.exists() or config_target.is_symlink():
        raise BackupError(
            "Target config path already exists; it will not be overwritten"
        )
    with tempfile.TemporaryDirectory(prefix="researchos-inspect-") as inspect_dir:
        dump_path = Path(inspect_dir) / "db.dump"
        with (
            zipfile.ZipFile(archive_path) as source,
            source.open("db.dump") as input_file,
            dump_path.open("wb") as output,
        ):
            while chunk := input_file.read(CHUNK_SIZE):
                output.write(chunk)
        with dump_path.open("rb") as input_file:
            _run_database(mode, "inspect", stdin=input_file, repo=repo)
    preflight_target(mode, target_db, attachments_target, config_target, repo=repo)
    if check_only:
        return manifest
    if confirm_target != target_db:
        raise BackupError(
            "Pass --confirm-target with the exact new database name to restore"
        )

    attachments_target.parent.mkdir(parents=True, exist_ok=True)
    config_target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="researchos-restore-", dir=attachments_target.parent
    ) as temporary:
        stage = Path(temporary)
        with zipfile.ZipFile(archive_path) as source:
            expected = {entry["path"]: entry for entry in manifest["files"]}
            dump_file = stage / "db.dump"
            _copy_verified_member(source, "db.dump", dump_file, expected["db.dump"])
            config_file = stage / "config.json"
            _copy_verified_member(
                source, "config.json", config_file, expected["config.json"]
            )
            attachment_files: list[tuple[Path, Path]] = []
            for entry in manifest["files"]:
                name = entry["path"]
                if not name.startswith("attachments/"):
                    continue
                relative = Path(*name.split("/")[1:])
                staged = stage / "attachments" / relative
                _copy_verified_member(source, name, staged, expected[name])
                attachment_files.append((staged, relative))

        # Reserve the destination before creating the DB. Never delete a failed DB restore:
        # it may contain useful diagnostics and automatic DROP would be destructive.
        attachments_target.mkdir(exist_ok=False)
        try:
            _run_database(mode, "create", target_db, repo=repo)
        except BaseException:
            attachments_target.rmdir()
            raise
        try:
            with dump_file.open("rb") as input_file:
                _run_database(mode, "restore", target_db, stdin=input_file, repo=repo)
            for staged, relative in attachment_files:
                target = attachments_target / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with staged.open("rb") as input_file, target.open("xb") as output:
                    while chunk := input_file.read(CHUNK_SIZE):
                        output.write(chunk)
            with (
                config_file.open("rb") as input_file,
                config_target.open("xb") as output,
            ):
                while chunk := input_file.read(CHUNK_SIZE):
                    output.write(chunk)
        except BaseException as exc:
            raise BackupError(
                f"Restore did not finish. New database '{target_db}' may be partial; inspect it and the new attachment directory manually."
            ) from exc
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--mode", choices=["compose", "local"], default="compose")
    parser.add_argument("--target-db")
    parser.add_argument("--attachments-target", type=Path)
    parser.add_argument("--config-target", type=Path)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify checksums without contacting PostgreSQL",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify archive and target availability without writing",
    )
    parser.add_argument(
        "--confirm-target", help="Exact new database name; required for restore"
    )
    args = parser.parse_args(argv)
    try:
        if args.verify_only:
            manifest = verify_archive(args.archive)
        else:
            if not args.target_db or not args.attachments_target:
                parser.error(
                    "--target-db and --attachments-target are required for --check or restore"
                )
            target = args.attachments_target
            config = args.config_target or target.with_name(
                f"{target.name}.config.json"
            )
            manifest = restore_backup(
                args.archive,
                mode=args.mode,
                target_db=args.target_db,
                attachments_target=target,
                config_target=config,
                confirm_target=args.confirm_target,
                check_only=args.check,
            )
    except (BackupError, OSError) as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1
    action = "Verified" if args.verify_only or args.check else "Restored"
    print(f"{action} backup with {manifest['attachments_count']} attachments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
