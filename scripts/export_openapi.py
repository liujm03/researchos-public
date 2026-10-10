"""Write or verify the FastAPI OpenAPI contract for frontend type generation."""

import argparse
import json
import sys
from pathlib import Path

from app.main import app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the saved contract differs")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = root / "packages" / "contracts" / "openapi.json"
    rendered = json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not target.is_file() or target.read_text(encoding="utf-8") != rendered:
            print("OpenAPI contract is stale; run scripts/export_openapi.py", file=sys.stderr)
            return 1
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
