"""Use the owner's existing Git Credential Manager login without exposing tokens."""
import os
import subprocess

from pydantic import SecretStr

from app.errors import DomainError


def github_credential(expected_login: str) -> SecretStr:
    """Credentials remain in process memory and the OS vault, never a receipt/log."""
    if not expected_login or any(c in expected_login for c in "\r\n="):
        raise DomainError("PROJECT_ARCHIVE_ACCOUNT_INVALID", "Invalid GitHub identity", 422)
    environment = dict(os.environ)
    environment.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"})
    try:
        response = subprocess.run(
            ["git", "credential-manager", "get"],
            input=f"protocol=https\nhost=github.com\nusername={expected_login}\n\n",
            capture_output=True, text=True, timeout=20, check=False, env=environment,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise DomainError("PROJECT_ARCHIVE_LOGIN_REQUIRED", "GitHub host authentication is unavailable", 503) from None
    if response.returncode or len(response.stdout) > 16384:
        raise DomainError("PROJECT_ARCHIVE_LOGIN_REQUIRED", "Sign in with Git Credential Manager", 503)
    values = dict(line.split("=", 1) for line in response.stdout.splitlines() if "=" in line)
    username, password = values.get("username"), values.get("password")
    if not username or username.casefold() != expected_login.casefold() or not password:
        raise DomainError("PROJECT_ARCHIVE_ACCOUNT_MISMATCH", "Cached GitHub account differs from the owner", 409)
    return SecretStr(password)
