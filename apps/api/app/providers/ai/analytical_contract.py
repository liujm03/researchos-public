"""Provider JSON schema and compatibility exports for the pure domain checks."""

import copy
from typing import Any

from app.domain.analytical_contract import (
    CANONICAL_HEADINGS as CANONICAL_HEADINGS,
)
from app.domain.analytical_contract import (
    UniqueKeysLoader as UniqueKeysLoader,
)
from app.domain.analytical_contract import (
    frontmatter as frontmatter,
)
from app.domain.analytical_contract import (
    validate_analytical_markdown as validate_analytical_markdown,
)
from app.providers.ai.analysis_contract import PAPER_ANALYSIS_SCHEMA

ANALYTICAL_NOTE_SCHEMA: dict[str, Any] = copy.deepcopy(PAPER_ANALYSIS_SCHEMA)
ANALYTICAL_NOTE_SCHEMA["properties"]["sections"].update({"minItems": 1, "maxItems": 1})
ANALYTICAL_NOTE_SCHEMA["properties"]["sections"]["items"]["properties"]["section_key"] = {
    "type": "string",
    "enum": ["analytical_note"],
}
