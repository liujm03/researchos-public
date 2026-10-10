import json
import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from pydantic import ValidationError

from app.domain.ai import (
    AIAnalysisResponse,
    AIUsage,
    PaperAnalysisRequest,
    PaperAnalysisResult,
)
from app.errors import DomainError
from app.providers.ai.analysis_contract import PAPER_ANALYSIS_SCHEMA, analysis_instructions

_BILLING_CODES = frozenset(
    {
        "organization_spend_limit_exceeded",
        "project_spend_limit_exceeded",
        "organization_usage_limit_exceeded",
        "insufficient_quota",
        "billing_hard_limit_reached",
    }
)


def _retry_after_seconds(value: str | None) -> int | None:
    if not value or len(value) > 128:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            deadline = parsedate_to_datetime(value)
            if deadline.tzinfo is None:
                return None
            seconds = (deadline.astimezone(UTC) - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return math.ceil(seconds)


def _usage_value(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _receipt(body: dict[str, Any]) -> dict[str, object]:
    raw_usage = body.get("usage")
    usage = raw_usage if isinstance(raw_usage, dict) else {}
    response_id = body.get("id")
    return {
        "usage": {
            "input_tokens": _usage_value(usage.get("input_tokens")),
            "output_tokens": _usage_value(usage.get("output_tokens")),
        },
        "provider_response_id": response_id
        if isinstance(response_id, str) and len(response_id) <= 200
        else None,
    }


class OpenAIResponsesProvider:
    provider_key = "openai"
    endpoint = "https://api.openai.com/v1/responses"

    def __init__(
        self,
        *,
        api_key: str,
        model_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key or not model_key:
            raise DomainError(
                "CAPABILITY_UNAVAILABLE", "OpenAI API key and model must be configured", 503
            )
        self.api_key = api_key
        self.model_key = model_key
        self.transport = transport

    async def analyze_paper(self, request: PaperAnalysisRequest) -> AIAnalysisResponse:
        if request.max_output_tokens is None:
            raise DomainError(
                "BUDGET_MODE_UNSUPPORTED", "OpenAI API calls require a local output limit", 409
            )
        source = {
            "title": request.title,
            "year": request.year,
            "abstract": request.abstract,
            "analysis_scope": request.scope,
            "analysis_mode": request.mode,
            "source_texts": [
                {
                    "section_key": part.section_key,
                    "text": part.text,
                    "page": part.page,
                    "block_index": part.block_index,
                    "title": part.title,
                    "ancestor_titles": list(part.ancestor_titles),
                }
                for part in request.source_texts
            ],
        }
        payload = {
            "model": self.model_key,
            "store": False,
            "instructions": analysis_instructions(request.scope),
            "input": json.dumps(source, ensure_ascii=False),
            "max_output_tokens": request.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "paper_research_note_v1",
                    "strict": True,
                    "schema": PAPER_ANALYSIS_SCHEMA,
                }
            },
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, read=120.0), transport=self.transport
            ) as client:
                response = await client.post(
                    self.endpoint,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
        except (httpx.ConnectTimeout, httpx.PoolTimeout, httpx.ConnectError) as exc:
            raise DomainError("AI_REQUEST_NOT_SENT", "AI request could not be sent", 503) from exc
        except httpx.RequestError as exc:
            # Read/write timeouts, disconnects and protocol/decoding failures do
            # not prove that the remote request was never executed or billed.
            raise DomainError(
                "AI_OUTCOME_UNCERTAIN",
                "AI request outcome is unknown; review before retrying",
                503,
            ) from exc
        if response.status_code == 429:
            try:
                error_body = response.json()
            except ValueError:
                error_body = None
            error = error_body.get("error") if isinstance(error_body, dict) else None
            if isinstance(error, dict) and (
                (isinstance(error.get("code"), str) and error.get("code") in _BILLING_CODES)
                or error.get("type") == "insufficient_quota"
            ):
                raise DomainError(
                    "AI_REQUEST_REJECTED", "AI billing or usage quota requires owner action", 503
                )
            delay = _retry_after_seconds(response.headers.get("Retry-After"))
            if delay is not None and delay > 3600:
                raise DomainError(
                    "AI_RATE_LIMIT_DEFERRED",
                    "AI retry delay exceeds the automatic limit; retry later",
                    429,
                )
            raise DomainError(
                "AI_RATE_LIMITED",
                "AI provider rate limit reached",
                429,
                details={"retry_after_seconds": delay} if delay is not None else None,
            )
        if response.status_code >= 500 or response.status_code == 408:
            raise DomainError(
                "AI_OUTCOME_UNCERTAIN",
                "AI server outcome is unknown; review before retrying",
                503,
            )
        if response.status_code >= 400:
            raise DomainError(
                "AI_REQUEST_REJECTED",
                f"AI provider rejected the request ({response.status_code})",
                503,
            )
        try:
            raw_body = response.json()
        except ValueError as exc:
            raise DomainError("AI_INVALID_OUTPUT", "AI response was not valid JSON", 502) from exc
        if not isinstance(raw_body, dict):
            raise DomainError("AI_INVALID_OUTPUT", "AI response was not an object", 502)
        body: dict[str, Any] = raw_body
        receipt = _receipt(body)
        if body.get("status") not in (None, "completed"):
            raise DomainError("AI_INCOMPLETE", "AI response did not complete", 503, details=receipt)
        outputs = body.get("output")
        if not isinstance(outputs, list):
            raise DomainError(
                "AI_INVALID_OUTPUT", "AI response has no structured output", 502, details=receipt
            )
        text_parts = [
            part.get("text", "")
            for output in outputs
            if isinstance(output, dict)
            and output.get("type") == "message"
            and isinstance(output.get("content"), list)
            for part in output["content"]
            if isinstance(part, dict)
            and part.get("type") == "output_text"
            and isinstance(part.get("text"), str)
        ]
        if not text_parts:
            raise DomainError(
                "AI_INVALID_OUTPUT", "AI provider returned no structured text", 502, details=receipt
            )
        try:
            result = PaperAnalysisResult.model_validate_json("".join(text_parts))
        except (ValidationError, ValueError) as exc:
            raise DomainError(
                "AI_INVALID_OUTPUT", "AI output failed schema validation", 502, details=receipt
            ) from exc
        raw_usage = body.get("usage")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        response_id = receipt["provider_response_id"]
        return AIAnalysisResponse(
            result=result,
            usage=AIUsage(
                input_tokens=_usage_value(usage.get("input_tokens")),
                output_tokens=_usage_value(usage.get("output_tokens")),
            ),
            provider_response_id=response_id if isinstance(response_id, str) else None,
        )
