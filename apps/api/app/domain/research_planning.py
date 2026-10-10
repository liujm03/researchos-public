"""Owner-granted tool-free research planning with actual frozen Skill sources."""

import hashlib
import json
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.ai import AIProviderDescriptor
from app.domain.pdf_reading import ReadingSkillSource
from app.errors import DomainError

PROFILES = ("scientific-brainstorming", "idea-evaluator")
PLANNING_CONTRACT_V1 = "planning-markdown-v1"
PLANNING_CONTRACT_V2 = "planning-brief-quotes-v2"
BRIEF_QUOTE_KEYS = (
    "intent",
    "related_work",
    "hypotheses",
    "resources",
    "routes",
    "protocol",
    "stage_plan",
    "decision",
)
PlanningQuoteKey = Literal[
    "intent",
    "related_work",
    "hypotheses",
    "resources",
    "routes",
    "protocol",
    "stage_plan",
    "decision",
]
PLANNING_ENCODER_VERSION = "json-utf8-ensure-ascii-false-allow-nan-false-v1"
PLANNING_TOOL_POLICY_VERSION = "verified-codex-paper-no-tools-v1"
PLANNING_INSTRUCTIONS_V1 = "\n输出只使用指定JSON包装：markdown字段完整保留本专业Skill的Markdown输出，不能自动接受Brief或改写任何科研记录。缺少实际检索/全文/实验时必须说明。输出额度跟随Codex账户，不估计账户余额或费用。"
PLANNING_INSTRUCTIONS_V2 = (
    PLANNING_INSTRUCTIONS_V1
    + "\n另给brief_quotes：八个固定key(intent/related_work/hypotheses/resources/routes/protocol/stage_plan/decision)各出现一次。quote仅可复制本次markdown里连续、逐字符相同的原文，保留Unicode、空白和缩进；不可重写、摘要或编造新内容。没有对应原文时填null。stop_rules_quote同样只能原文引用或null；warnings记录映射缺口。程序只定位这些引用，不自动接受或改写任务书。"
)
PLANNING_SCHEMA_V1: dict[str, object] = {
    "type": "object",
    "properties": {"markdown": {"type": "string"}},
    "required": ["markdown"],
    "additionalProperties": False,
}
PLANNING_SCHEMA_V2: dict[str, object] = {
    "type": "object",
    "properties": {
        "markdown": {"type": "string"},
        "brief_quotes": {
            "type": "object",
            "properties": {
                "sections": {
                    "type": "array",
                    "minItems": 8,
                    "maxItems": 8,
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "enum": list(BRIEF_QUOTE_KEYS)},
                            "quote": {"type": ["string", "null"], "maxLength": 40000},
                        },
                        "required": ["key", "quote"],
                        "additionalProperties": False,
                    },
                },
                "stop_rules_quote": {"type": ["string", "null"], "maxLength": 40000},
                "warnings": {
                    "type": "array",
                    "maxItems": 20,
                    "items": {"type": "string", "maxLength": 2000},
                },
            },
            "required": ["sections", "stop_rules_quote", "warnings"],
            "additionalProperties": False,
        },
    },
    "required": ["markdown", "brief_quotes"],
    "additionalProperties": False,
}


def planning_contract(version: str) -> tuple[dict[str, object], str]:
    if version == PLANNING_CONTRACT_V1:
        return deepcopy(PLANNING_SCHEMA_V1), PLANNING_INSTRUCTIONS_V1
    if version == PLANNING_CONTRACT_V2:
        return deepcopy(PLANNING_SCHEMA_V2), PLANNING_INSTRUCTIONS_V2
    raise DomainError(
        "PLANNING_CONTRACT_UNSUPPORTED",
        "Planning output contract is not supported",
        409,
        details={"submitted": False},
    )


def output_contract_payload(version: str) -> dict[str, object]:
    schema, instructions = planning_contract(version)
    return {
        "version": version,
        "schema": deepcopy(schema),
        "instructions": instructions,
        "encoder_version": PLANNING_ENCODER_VERSION,
        "tool_policy_version": PLANNING_TOOL_POLICY_VERSION,
    }


def planning_contract_sha256(version: str) -> str:
    return hashlib.sha256(
        json.dumps(
            output_contract_payload(version),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def validate_planning_contract(version: str, expected_sha256: str | None) -> None:
    actual = planning_contract_sha256(version)
    if (
        version != PLANNING_CONTRACT_V1 or expected_sha256 is not None
    ) and actual != expected_sha256:
        raise DomainError(
            "PLANNING_CONTRACT_CHANGED",
            "Frozen output contract differs from the executing adapter",
            409,
            details={"submitted": False},
        )


class PlanningBriefQuoteSection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key: PlanningQuoteKey
    quote: str | None = Field(max_length=40000)
    uncertainty: str | None = Field(default=None, max_length=2000)


class PlanningBriefQuotes(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sections: list[PlanningBriefQuoteSection] = Field(min_length=8, max_length=8)
    stop_rules_quote: str | None = Field(default=None, max_length=40000)
    warnings: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def exact_sections(self) -> "PlanningBriefQuotes":
        if len({item.key for item in self.sections}) != 8 or {
            item.key for item in self.sections
        } != set(BRIEF_QUOTE_KEYS):
            raise ValueError("Eight distinct fixed section keys are required")
        if any(len(warning) > 2000 for warning in self.warnings):
            raise ValueError("Warning bound")
        return self


def planning_quote_spans(
    markdown: str, quotes: PlanningBriefQuotes
) -> dict[str, tuple[int, int] | None]:
    result: dict[str, tuple[int, int] | None] = {}
    values = [(item.key, item.quote) for item in quotes.sections] + [
        ("stop_rules", quotes.stop_rules_quote)
    ]
    for key, quote in values:
        if quote is None:
            result[key] = None
            continue
        if not quote.strip() or len(quote) > 40000:
            raise DomainError(
                "PLANNING_QUOTE_INVALID", "Planning quote is empty or exceeds its bound", 422
            )
        start = markdown.find(quote)
        if start < 0:
            raise DomainError(
                "PLANNING_QUOTE_NOT_FOUND", "Planning quote is not exact original Markdown", 422
            )
        result[key] = start, start + len(quote)
    return result


def planning_sources_sha256(files: tuple[ReadingSkillSource, ...]) -> str:
    value = [
        {"path": item.path, "role": item.role, "sha256": item.sha256, "size_bytes": item.size_bytes}
        for item in sorted(files, key=lambda item: (item.path, item.role))
    ]
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class PlanningSkillReceipt:
    profile: str
    key: str
    version: str
    manifest_sha256: str
    instructions_sha256: str
    instructions: str
    files: tuple[ReadingSkillSource, ...]
    warnings: tuple[str, ...] = ()


class PlanningSkillProvider(Protocol):
    def load(self, profile: str) -> PlanningSkillReceipt: ...


@dataclass(frozen=True)
class PlanningRequest:
    job_id: uuid.UUID
    attempt_id: uuid.UUID
    manifest_sha256: str
    model_key: str
    reasoning_effort: str
    focus: str
    input_snapshot: dict[str, object]
    skill_instructions: str
    timeout_seconds: int
    permit_nonce: uuid.UUID | None = None
    output_contract_version: str = PLANNING_CONTRACT_V1
    output_contract_sha256: str | None = None


@dataclass(frozen=True)
class PlanningResponse:
    markdown: str
    provider_response_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    normalization: PlanningBriefQuotes | None = None
    normalization_issue: str | None = None


class ResearchPlanningProvider(Protocol):
    def descriptor(self) -> AIProviderDescriptor: ...

    async def plan(self, request: PlanningRequest) -> PlanningResponse: ...
