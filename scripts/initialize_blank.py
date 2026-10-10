"""Create a new installation's secrets without copying an existing owner's config."""

from __future__ import annotations

import argparse
import re
import secrets
from pathlib import Path


def initialize(root: Path, mode: str) -> Path:
    if mode not in {"compose", "local"}:
        raise ValueError("Choose compose or local deployment")
    root = root.resolve()
    target = root / ".env"
    if target.exists() or target.is_symlink():
        raise ValueError(
            "Existing .env was preserved; choose a new installation directory"
        )
    template = root / ".env.example"
    if template.is_symlink():
        raise ValueError("Linked configuration template refused")
    password = secrets.token_urlsafe(40)
    values = {
        "APP_ENV": "production",
        "WEB_PORT": "3100",
        "API_PORT": "8100",
        "POSTGRES_PASSWORD": password,
        "SESSION_SECRET": secrets.token_urlsafe(48),
        "CSRF_SECRET": secrets.token_urlsafe(48),
        "INITIAL_SETUP_TOKEN": secrets.token_urlsafe(40),
        "DATABASE_URL": f"postgresql+psycopg://researchos:{password}@postgres:5432/researchos",
        "API_INTERNAL_URL": "http://api:8000",
        "ANALYTICAL_NOTE_ROOT": "./data/analytical-notes",
    }
    if mode == "local":
        values.update(
            DATABASE_URL=f"postgresql+psycopg://researchos:{password}@127.0.0.1:55432/researchos",
            API_INTERNAL_URL="http://127.0.0.1:8100",
            LOCAL_STORAGE_ROOT=(root / "data/attachments").as_posix(),
            BACKUP_ROOT=(root / "data/backups").as_posix(),
            ANALYTICAL_NOTE_ROOT=(root / "data/analytical-notes").as_posix(),
        )
    rows = template.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    output: list[str] = []
    deployment = {
        "RESEARCHOS_DEPLOYMENT": mode,
        "COMPOSE_PROJECT_NAME": f"researchos_{secrets.token_hex(6)}",
    }
    for row in rows:
        match = re.match(r"^([A-Z_][A-Z0-9_]*)=", row)
        if match:
            key = match.group(1)
            if key in seen:
                raise ValueError("Duplicate template setting")
            seen.add(key)
            replacements = values | deployment
            row = f"{key}={replacements[key]}" if key in replacements else row
        output.append(row)
    if not values.keys() <= seen:
        raise ValueError("Configuration template is incomplete")
    output.extend(
        f"{key}={value}" for key, value in deployment.items() if key not in seen
    )
    with target.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(output) + "\n")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("compose", "local"), default="compose")
    args = parser.parse_args()
    initialize(Path(__file__).resolve().parents[1], args.mode)
    print(
        "Created your local .env. Secrets were not printed. Read INSTALL.md before starting."
    )


if __name__ == "__main__":
    main()
