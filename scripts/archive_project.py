"""Freeze, publish and recover an independently bound private project code version.

Run with the ResearchOS Python environment. No secrets are accepted as arguments.
Local receipts reside inside .git; version manifests are embedded in archive commits.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))

from app.domain.github_archive import GitHubPrivateRepository
from app.domain.project_archive import (
    LocalProjectVersionReceipt,
    ProjectVersionManifest,
)
from app.errors import DomainError
from app.providers.code_changes.local import LocalCodeFileProvider
from app.providers.project_archives.credentials import github_credential
from app.providers.project_archives.git_transport import (
    GitHubGitTransport,
)
from app.providers.project_archives.github import (
    GitHubProjectArchiveAdapter,
)
from app.providers.project_archives.local_git import (
    VERSION,
    LocalGitProjectVersionProvider,
)
from app.services.project_archive_publish import publish_version


def read_record[T](path: Path, record_type: type[T]) -> T:
    if path.stat().st_size > 2 * 1024 * 1024:
        raise DomainError("ARCHIVE_RECORD_INVALID", "Local archive record exceeds its size bound")
    return TypeAdapter(record_type).validate_json(path.read_bytes())


def save_record(path: Path, value: object) -> None:
    """Exclusive receipt creation: never replace an existing binding or version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != value:
            raise DomainError("ARCHIVE_RECORD_CONFLICT", "Existing archive record differs; retain both states", 409)
        return
    with path.open("x", encoding="utf-8") as stream:
        stream.write(rendered)


async def execute(args: argparse.Namespace) -> object:
    root = Path(args.root).resolve(strict=True)
    LocalGitProjectVersionProvider(root)._root()
    guard = LocalCodeFileProvider(root)
    with guard.exclusive():
        guard.assert_no_pending_changes()
        return await _execute_locked(args)


async def _execute_locked(args: argparse.Namespace) -> object:
    root = Path(args.root).resolve(strict=True)
    local = LocalGitProjectVersionProvider(root)
    # Validate the dedicated root and all metadata ancestors before reading receipts.
    local._root()
    state = root / ".git" / "researchos"
    if args.command == "restore":
        return asdict(local.restore_version(args.version, args.destination))
    if args.command == "bind":
        if args.create and (state / "binding.json").exists():
            raise DomainError("ARCHIVE_ALREADY_BOUND", "This project already has a repository binding; do not create another destination", 409)
        credential = github_credential(args.account)
        provider = GitHubProjectArchiveAdapter(token=credential.get_secret_value())
        await provider.inspect_authenticated_account(args.account, args.account_id)
        if args.create:
            created = await provider.create_private_repository(args.account, args.repository, expected_owner_id=args.account_id)
            if created.reconciled_after_unknown:
                raise DomainError("ARCHIVE_BINDING_NEEDS_REVIEW", "Creation acknowledgment was lost; review the observed repository ID, then bind with --repository-id", 409)
            repository = created.repository
        else:
            if args.repository_id is None:
                raise DomainError("ARCHIVE_BINDING_ID_REQUIRED", "An existing repository requires its verified numeric ID")
            repository = await provider.get_private_owned_repository(args.account, args.repository, expected_owner_id=args.account_id, expected_repository_id=args.repository_id)
        binding = {"project_id": args.project, "repository": asdict(repository)}
        save_record(state / "binding.json", binding)
        return binding
    binding_path = state / "binding.json"
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    repository = TypeAdapter(GitHubPrivateRepository).validate_python(binding["repository"])
    project_id = str(binding["project_id"])
    owner_id = "github:" + str(repository.owner_id)
    if not VERSION.fullmatch(args.version):
        raise DomainError("ARCHIVE_VERSION_INVALID", "Use an immutable semantic version tag")
    manifest_path = state / "manifests" / (args.version + ".json")
    receipt_path = state / "versions" / (args.version + ".json")
    if args.command == "preflight":
        manifest = local.preflight(owner_id=owner_id, project_id=project_id, version=args.version)
        if args.refresh and manifest_path.exists():
            # preflight already rejects committed tags; replace only this unpublished
            # candidate, never a binding, version receipt or published manifest.
            refreshed = manifest_path.with_suffix(".refresh.json")
            save_record(refreshed, json.loads(json.dumps(asdict(manifest))))
            refreshed.replace(manifest_path)
        # JSON roundtrip normalizes immutable tuples to arrays for repeat comparison.
        save_record(manifest_path, json.loads(json.dumps(asdict(manifest))))
        return {"manifest": str(manifest_path), "sha256": manifest.sha256, "files": len(manifest.files), "bytes": sum(row.size_bytes for row in manifest.files), "excluded": [asdict(row) for row in manifest.excluded]}
    if args.command == "commit":
        manifest = read_record(manifest_path, ProjectVersionManifest)
        if (manifest.owner_id, manifest.project_id, manifest.version) != (owner_id, project_id, args.version):
            raise DomainError("ARCHIVE_BINDING_MISMATCH", "Frozen manifest does not match the current project binding", 409)
        receipt = local.commit_version(manifest, author_name=args.author_name, author_email=args.author_email)
        save_record(receipt_path, asdict(receipt))
        return asdict(receipt)
    receipt = read_record(receipt_path, LocalProjectVersionReceipt)
    if (receipt.owner_id, receipt.project_id, receipt.version, receipt.tag) != (owner_id, project_id, args.version, args.version):
        raise DomainError("ARCHIVE_BINDING_MISMATCH", "Local version does not match the current project binding", 409)
    credential = github_credential(repository.owner_login)
    provider = GitHubProjectArchiveAdapter(token=credential.get_secret_value())
    published = await publish_version(root, repository, receipt, provider=provider, transport=GitHubGitTransport())
    save_record(state / "publications" / (args.version + ".json"), asdict(published))
    return asdict(published)


def main() -> int:
    # Machine-readable receipts use UTF-8 even when Windows pipes inherit GBK.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="strict")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Dedicated project Git root")
    commands = parser.add_subparsers(dest="command", required=True)
    bind = commands.add_parser("bind", help="Explicitly bind one private repository")
    bind.add_argument("--project", required=True)
    bind.add_argument("--account", required=True)
    bind.add_argument("--account-id", required=True, type=int)
    bind.add_argument("--repository", required=True)
    group = bind.add_mutually_exclusive_group(required=True)
    group.add_argument("--create", action="store_true")
    group.add_argument("--repository-id", type=int)
    for command in ("preflight", "commit", "publish", "restore"):
        sub = commands.add_parser(command)
        sub.add_argument("--version", required=True)
        if command == "preflight":
            sub.add_argument("--refresh", action="store_true", help="Explicitly replace an unpublished frozen candidate after source edits")
        if command == "commit":
            sub.add_argument("--author-name", required=True)
            sub.add_argument("--author-email", required=True)
        if command == "restore":
            sub.add_argument("--destination", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(execute(args)), ensure_ascii=False, indent=2))
        return 0
    except DomainError as error:
        print(json.dumps({"code": error.code, "message": error.message, "details": error.details}, ensure_ascii=False), file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError, ValidationError):
        # Never echo raw credential/configuration values in parser/validation errors.
        print("Archive failed: local record or filesystem state is invalid; no success inferred", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
