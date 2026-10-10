"""Raw professional Skill Markdown via the existing restricted Codex runtime."""

import asyncio
import json
from typing import Any

from app.domain.ai import AIProviderDescriptor
from app.domain.research_planning import (
    PLANNING_CONTRACT_V1,
    PLANNING_CONTRACT_V2,
    PLANNING_SCHEMA_V1,
    PlanningBriefQuotes,
    PlanningRequest,
    PlanningResponse,
    planning_contract,
    planning_quote_spans,
    validate_planning_contract,
)
from app.errors import DomainError
from app.providers.ai.codex_paper import CodexPaperRuntime, _SDKRuntime, _tokens

MAX_OUTPUT_BYTES = 1_048_576
MAX_INPUT_BYTES = 2 * 1024 * 1024
MARKDOWN_SCHEMA = PLANNING_SCHEMA_V1


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


class _Pairs(list[tuple[str, object]]):
    """Keep secondary duplicate keys observable without losing the primary Markdown."""


def _plain(value: object) -> object:
    if isinstance(value, _Pairs):
        return {key: _plain(item) for key, item in _unique(value).items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


class CodexResearchPlanningProvider:
    def __init__(
        self,
        *,
        model_key: str,
        reasoning_effort: str = "max",
        runtime: CodexPaperRuntime | None = None,
    ) -> None:
        self.model_key = model_key
        self.reasoning_effort = reasoning_effort
        self.runtime = runtime if runtime is not None else _SDKRuntime()

    def descriptor(self) -> AIProviderDescriptor:
        if not self.model_key.strip() or not self.reasoning_effort.strip():
            return AIProviderDescriptor(
                "codex",
                self.model_key or None,
                False,
                False,
                "PLANNING_CONFIGURATION_CHANGED",
                "Configure the explicit planning model and reasoning effort",
            )
        try:
            return self.runtime.inspect(self.model_key)
        except Exception:
            return AIProviderDescriptor(
                "codex",
                self.model_key,
                True,
                False,
                "CODEX_RUNTIME_UNAVAILABLE",
                "Research planning runtime readiness could not be verified",
            )

    async def plan(self, request: PlanningRequest) -> PlanningResponse:
        validate_planning_contract(request.output_contract_version, request.output_contract_sha256)
        schema, supplement = planning_contract(request.output_contract_version)
        if (
            request.model_key != self.model_key
            or request.reasoning_effort != self.reasoning_effort
            or not request.skill_instructions.strip()
            or not 0 < request.timeout_seconds <= 3600
        ):
            raise DomainError(
                "PLANNING_CONFIGURATION_CHANGED",
                "Frozen planning model or instructions are unavailable or changed",
                409,
                details={"submitted": False},
            )
        try:
            prompt = json.dumps(
                {
                    "job_id": str(request.job_id),
                    "attempt_id": str(request.attempt_id),
                    "manifest_sha256": request.manifest_sha256,
                    "owner_focus": request.focus,
                    "approved_brief_and_metadata": request.input_snapshot,
                },
                ensure_ascii=False,
                allow_nan=False,
            )
        except (ValueError, TypeError):
            raise DomainError(
                "PLANNING_INPUT_INVALID",
                "Frozen planning input is not bounded JSON",
                422,
                details={"submitted": False},
            ) from None
        if (
            len(prompt.encode("utf-8")) > MAX_INPUT_BYTES
            or len(request.skill_instructions.encode("utf-8")) > 256000
        ):
            raise DomainError(
                "PLANNING_INPUT_INVALID",
                "Frozen planning input exceeds the technical size bound",
                422,
                details={"submitted": False},
            )
        available = await asyncio.to_thread(self.descriptor)
        if not available.available or available.model_key != request.model_key:
            raise DomainError(
                available.reason_code or "CODEX_RUNTIME_UNAVAILABLE",
                "Planning runtime is unavailable; no model call was submitted",
                503,
                details={"submitted": False},
            )
        instructions = request.skill_instructions + supplement
        try:
            async with asyncio.timeout(request.timeout_seconds + 30):
                receipt = await self.runtime.analyze(
                    model=request.model_key,
                    prompt=prompt,
                    instructions=instructions,
                    output_schema=schema,
                    timeout_seconds=request.timeout_seconds,
                    max_output_tokens=None,
                    page_images=(),
                    reasoning_effort=request.reasoning_effort,
                )
        except DomainError as error:
            details = error.details if isinstance(error.details, dict) else {}
            if (
                error.code == "AI_INVALID_OUTPUT"
                and details.get("submission_attempted") is True
                and details.get("turn_status") != "completed"
            ):
                raise DomainError(
                    "AI_OUTCOME_UNCERTAIN",
                    "Planning stream exceeded a bound before terminal completion; stopping was not confirmed",
                    503,
                    details=details,
                ) from None
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            raise DomainError(
                "AI_OUTCOME_UNCERTAIN",
                "Planning provider outcome is unknown; never replay without owner reconciliation",
                503,
            ) from None
        response_id = (
            receipt.response_id
            if isinstance(receipt.response_id, str)
            and len(receipt.response_id) <= 200
            and "\0" not in receipt.response_id
            else None
        )
        usage: dict[str, Any] = {
            "provider_response_id": response_id,
            "provider_completed": receipt.completed,
            "usage": {
                "input_tokens": _tokens(receipt.input_tokens),
                "output_tokens": _tokens(receipt.output_tokens),
            },
        }
        if not receipt.completed:
            raise DomainError(
                "AI_OUTCOME_UNCERTAIN",
                "Planning turn did not confirm completion",
                503,
                details=usage,
            )
        try:
            wrapper_limit = (
                MAX_OUTPUT_BYTES + 16384
                if request.output_contract_version == PLANNING_CONTRACT_V1
                else MAX_OUTPUT_BYTES * 3 + 16384
            )
            if len(receipt.output_text.encode("utf-8")) > wrapper_limit:
                raise ValueError("wrapper size")
            if request.output_contract_version == PLANNING_CONTRACT_V1:
                parsed: object = json.loads(receipt.output_text, object_pairs_hook=_unique)
                if (
                    not isinstance(parsed, dict)
                    or set(parsed) != {"markdown"}
                    or not isinstance(parsed["markdown"], str)
                ):
                    raise ValueError("wrapper")
                markdown = parsed["markdown"]
            else:
                parsed = json.loads(receipt.output_text, object_pairs_hook=_Pairs)
                if not isinstance(parsed, _Pairs):
                    raise ValueError("wrapper")
                primary = [value for key, value in parsed if key == "markdown"]
                if len(primary) != 1 or not isinstance(primary[0], str):
                    raise ValueError("ambiguous primary Markdown")
                markdown = primary[0]
            if (
                not markdown.strip()
                or "\0" in markdown
                or len(markdown.encode("utf-8")) > MAX_OUTPUT_BYTES
            ):
                raise ValueError("markdown bound")
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise DomainError(
                "AI_INVALID_OUTPUT",
                "Completed planning output failed the Markdown wrapper contract",
                502,
                details=usage,
            ) from None
        normalization, normalization_issue = None, None
        if request.output_contract_version == PLANNING_CONTRACT_V2:
            try:
                wrapper = _plain(parsed)
                if not isinstance(wrapper, dict) or set(wrapper) != {"markdown", "brief_quotes"}:
                    raise ValueError("secondary wrapper")
                mapping = wrapper["brief_quotes"]
                if (
                    not isinstance(mapping, dict)
                    or set(mapping) != {"sections", "stop_rules_quote", "warnings"}
                    or not isinstance(mapping["sections"], list)
                    or any(
                        not isinstance(item, dict) or set(item) != {"key", "quote"}
                        for item in mapping["sections"]
                    )
                ):
                    raise ValueError("secondary contract fields")
                normalization = PlanningBriefQuotes.model_validate(mapping)
                planning_quote_spans(markdown, normalization)
            except DomainError as error:
                normalization, normalization_issue = None, error.code
            except (ValueError, TypeError, RecursionError):
                normalization, normalization_issue = None, "PLANNING_NORMALIZATION_INVALID"
        return PlanningResponse(
            markdown,
            response_id,
            _tokens(receipt.input_tokens),
            _tokens(receipt.output_tokens),
            normalization,
            normalization_issue,
        )
