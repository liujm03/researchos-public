"""Exact ordinary Git ref transfer through the owner's OS credential manager."""

import os
import re
import subprocess
from pathlib import Path

from app.domain.github_archive import GitHubPrivateRepository
from app.domain.project_archive import LocalProjectVersionReceipt
from app.errors import DomainError

_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
_NAME = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
_SHA = re.compile(r"[a-f0-9]{40}\Z")
_VERSION = re.compile(r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*)?\Z")
_FORBIDDEN_CONFIG = (
    r"^(include\.|includeif\.|extensions\.|url\.|http\.|credential\.|"
    r"remote\.|push\.|submodule\.|protocol\.|core\.(sshcommand|gitproxy))"
)


def _pre_push_run(arguments: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            arguments, capture_output=True, env=environment, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        # Git diagnostics can contain URLs, config values and credential helpers.
        raise DomainError(
            "PROJECT_ARCHIVE_TRANSPORT_UNAVAILABLE",
            "Local Git checks could not complete; no push was started", 503,
        ) from None


class GitHubGitTransport:
    def push(self, root: Path, repository: GitHubPrivateRepository, receipt: LocalProjectVersionReceipt) -> None:
        if repository.private is not True or repository.push_allowed is not True:
            raise DomainError("PROJECT_ARCHIVE_REMOTE_REJECTED", "A writable private repository is required", 409)
        if (
            not _LOGIN.fullmatch(repository.owner_login) or "--" in repository.owner_login
            or not _NAME.fullmatch(repository.name) or repository.name in {".", ".."}
            or type(repository.owner_id) is not int or repository.owner_id <= 0
            or type(repository.repository_id) is not int or repository.repository_id <= 0
            or not _VERSION.fullmatch(receipt.tag) or receipt.tag != receipt.version
            or not _SHA.fullmatch(receipt.commit_sha)
        ):
            raise DomainError("PROJECT_ARCHIVE_IDENTITY_INVALID", "Invalid bound repository or frozen version identity", 422)
        environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        environment.update({
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never",
        })
        base = [
            "git", "-c", "core.hooksPath=" + os.devnull,
            "-c", "credential.helper=", "-c", "credential.helper=manager",
            "-c", "http.sslVerify=true", "-c", "http.followRedirects=false",
            "-c", "push.followTags=false", "-c", "push.recurseSubmodules=no",
            "-C", str(root),
        ]
        # Read local keys without expanding include files. Includes, worktree
        # config, credential policies and push defaults require review rather
        # than silently redirecting or widening a transfer.
        config = _pre_push_run(base + [
            "config", "--local", "--no-includes", "--name-only", "--get-regexp",
            _FORBIDDEN_CONFIG,
        ], environment)
        if config.returncode not in {0, 1} or (config.returncode == 1 and config.stdout):
            raise DomainError("PROJECT_ARCHIVE_TRANSPORT_UNAVAILABLE", "Local Git transport policy could not be verified; no push was started", 503)
        if config.returncode == 0:
            raise DomainError("PROJECT_ARCHIVE_TRANSPORT_POLICY", "Repository-local transport overrides require review", 409)
        refs = ("refs/heads/researchos-archive", "refs/tags/" + receipt.tag)
        for ref in refs:
            resolved = _pre_push_run(base + ["rev-parse", "--verify", ref], environment)
            if resolved.returncode or resolved.stdout.strip() != receipt.commit_sha.encode("ascii"):
                raise DomainError("PROJECT_ARCHIVE_LOCAL_REF_CHANGED", "Frozen local version ref changed before push", 409)
        target = f"https://{repository.owner_login}@github.com/{repository.full_name}.git"
        try:
            pushed = subprocess.run(
                # Transfer the frozen object, not a branch that could move after
                # the checks. Ordinary remote fast-forward rules still apply.
                base + ["push", "--atomic", "--porcelain", target, *(receipt.commit_sha + ":" + ref for ref in refs)],
                capture_output=True, env=environment, timeout=180, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise DomainError("PROJECT_ARCHIVE_PUSH_UNKNOWN", "Push outcome is unknown; inspect remote refs before any retry", 503) from None
        if pushed.returncode:
            raise DomainError("PROJECT_ARCHIVE_PUSH_UNCONFIRMED", "Remote push was not confirmed; retained local version needs ref inspection", 503)
