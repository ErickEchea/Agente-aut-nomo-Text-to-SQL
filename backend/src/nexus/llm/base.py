"""Provider-neutral types for structured LLM calls."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class GenerationOptions:
    """Deterministic by default: temperature 0 and a fixed seed make runs reproducible."""

    model: str | None = None  # None → the provider's default model
    temperature: float = 0.0
    seed: int = 7
    num_ctx: int = 8192
    max_tokens: int | None = 1024
    think: bool | None = None  # only sent to models that support a reasoning toggle


@dataclass(frozen=True, slots=True)
class TokenUsage:
    model: str
    prompt_tokens: int
    completion_tokens: int
    duration_ms: float

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class Completion[T: BaseModel]:
    parsed: T
    raw: str
    usage: TokenUsage


class LLMError(Exception):
    """The provider failed (unreachable, model missing, server error)."""


class StructuredOutputError(LLMError):
    """The model answered, but not with JSON matching the requested schema."""

    def __init__(self, message: str, raw: str, usage: TokenUsage) -> None:
        super().__init__(message)
        self.raw = raw
        self.usage = usage


class LLMProvider(Protocol):
    @property
    def default_model(self) -> str: ...

    async def complete[T: BaseModel](
        self,
        messages: Sequence[Message],
        schema: type[T],
        options: GenerationOptions | None = None,
    ) -> Completion[T]:
        """Generate a response constrained to ``schema`` and validate it."""
        ...

    async def embed(self, texts: Sequence[str], model: str | None = None) -> list[list[float]]: ...
