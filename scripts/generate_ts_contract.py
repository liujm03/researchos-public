"""Generate the frontend's TypeScript schema aliases from FastAPI OpenAPI.

This small generator intentionally handles the schema forms emitted by this API.
It fails on unknown forms, so a new Pydantic shape cannot silently become `any`.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

root = Path(__file__).resolve().parents[1]
source = root / "packages" / "contracts" / "openapi.json"
target = root / "apps" / "web" / "src" / "lib" / "generated.ts"
document = json.loads(source.read_text(encoding="utf-8"))
schemas: dict[str, dict[str, Any]] = document["components"]["schemas"]


def ts_type(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return f'components["schemas"]["{name}"]'
    if "enum" in schema:
        return " | ".join(json.dumps(value, ensure_ascii=False) for value in schema["enum"])
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    if "anyOf" in schema or "oneOf" in schema:
        return " | ".join(ts_type(part) for part in schema.get("anyOf", schema.get("oneOf", [])))
    if "allOf" in schema:
        return " & ".join(ts_type(part) for part in schema["allOf"])
    kind = schema.get("type")
    if kind == "null":
        return "null"
    if kind == "string":
        return "string"
    if kind in ("integer", "number"):
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "array":
        return f"({ts_type(schema['items'])})[]"
    if kind == "object" or "properties" in schema:
        fields: list[str] = []
        required = set(schema.get("required", []))
        for name, field in schema.get("properties", {}).items():
            optional = "" if name in required else "?"
            fields.append(f"{json.dumps(name)}{optional}: {ts_type(field)};")
        additional = schema.get("additionalProperties")
        if additional is not None:
            if additional is True:
                fields.append("[key: string]: unknown;")
            elif isinstance(additional, dict):
                fields.append(f"[key: string]: {ts_type(additional)};")
            elif additional is False:
                # Closed Pydantic schemas have only the declared properties.
                # TypeScript excess-property checks enforce this on literals;
                # runtime validation remains the API's responsibility.
                pass
            else:
                raise ValueError(f"Unsupported additionalProperties: {additional!r}")
        return "{ " + " ".join(fields) + " }"
    if set(schema).issubset({"title", "description", "default"}):
        return "unknown"
    raise ValueError(f"Unsupported OpenAPI schema: {schema!r}")


lines = [
    "// Generated from packages/contracts/openapi.json. Do not edit by hand.",
    "export interface components {",
    "  schemas: {",
]
for name, schema in sorted(schemas.items()):
    lines.append(f"    {json.dumps(name)}: {ts_type(schema)};")
lines.extend(["  };", "}", ""])
rendered = "\n".join(lines)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--check", action="store_true", help="Fail if generated TypeScript differs")
args = parser.parse_args()
if args.check:
    if not target.is_file() or target.read_text(encoding="utf-8") != rendered:
        print("TypeScript API types are stale; run scripts/generate_ts_contract.py", file=sys.stderr)
        raise SystemExit(1)
else:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
print(target)
