"""Codex execution port. Business services do not import an SDK."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

CodexMode = Literal["read_only", "workspace_write"]
CodexBudgetMode = Literal["LOCAL_LIMITS", "PROVIDER_QUOTA"]
CodexRunStatus = Literal["COMPLETED", "CANCELLED", "FAILED", "NEEDS_ATTENTION"]
EventSink = Callable[[str, str], Awaitable[None]]
StartedSink = Callable[[str, str], Awaitable[None]]
CancelCheck = Callable[[], Awaitable[bool]]
CODEX_NO_EXECUTION_CONTRACT = "NO_EXECUTION_TOOLS_V1"


@dataclass(frozen=True)
class CodexRunRequest:
    prompt: str
    workspace_path: str
    mode: CodexMode
    model: str | None
    timeout_seconds: int = 1800
    max_tokens: int | None = 100_000
    reasoning_effort: str | None = None
    budget_mode: CodexBudgetMode = "LOCAL_LIMITS"
    output_format: Literal["MARKDOWN", "CODE_CHANGE_JSON"] = "MARKDOWN"


@dataclass(frozen=True)
class CodexRunResult:
    status: CodexRunStatus
    final_response: str | None = None
    error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    token_budget_exceeded: bool = False


@dataclass(frozen=True)
class CodexRuntimeCapabilities:
    sdk_installed: bool
    authenticated: bool
    reason: str | None = None


class CodexProvider(Protocol):
    provider_key: str

    def probe(self) -> CodexRuntimeCapabilities: ...

    async def run(
        self,
        request: CodexRunRequest,
        emit: EventSink,
        on_started: StartedSink,
        cancel_requested: CancelCheck,
    ) -> CodexRunResult: ...
