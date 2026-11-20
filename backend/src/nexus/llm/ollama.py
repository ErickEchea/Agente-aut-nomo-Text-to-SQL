"""Ollama implementation of :class:`LLMProvider` using JSON-schema structured outputs."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import httpx
import ollama
from pydantic import BaseModel, ValidationError

from nexus.llm.base import (
    Completion,
    GenerationOptions,
    LLMError,
    Message,
    StructuredOutputError,
    TokenUsage,
)


class OllamaProvider:
    def __init__(
        self,
        base_url: str,
        default_model: str,
        embedding_model: str,
        *,
        timeout_s: float = 120.0,
        keep_alive: str = "30m",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        client_kwargs: dict[str, Any] = {"timeout": timeout_s}
        if transport is not None:
            client_kwargs["transport"] = transport
        self._client = ollama.AsyncClient(host=base_url, **client_kwargs)
        self._default_model = default_model
        self._embedding_model = embedding_model
        self._keep_alive = keep_alive

    @property
    def default_model(self) -> str:
        return self._default_model

    async def complete[T: BaseModel](
        self,
        messages: Sequence[Message],
        schema: type[T],
        options: GenerationOptions | None = None,
    ) -> Completion[T]:
        opts = options or GenerationOptions()
        model = opts.model or self._default_model
        model_options: dict[str, Any] = {
            "temperature": opts.temperature,
            "seed": opts.seed,
            "num_ctx": opts.num_ctx,
        }
        if opts.max_tokens is not None:
            model_options["num_predict"] = opts.max_tokens
        extra: dict[str, Any] = {}
        if opts.think is not None:
            extra["think"] = opts.think

        started = time.perf_counter()
        try:
            response = await self._client.chat(
                model=model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                format=schema.model_json_schema(),
                options=model_options,
                keep_alive=self._keep_alive,
                **extra,
            )
        except ollama.ResponseError as exc:
            raise LLMError(f"ollama error ({exc.status_code}): {exc.error}") from exc
        except (httpx.HTTPError, ConnectionError) as exc:  # the client maps ConnectError
            raise LLMError(f"ollama unreachable: {type(exc).__name__}") from exc

        raw = response.message.content or ""
        usage = TokenUsage(
            model=model,
            prompt_tokens=response.prompt_eval_count or 0,
            completion_tokens=response.eval_count or 0,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        try:
            parsed = schema.model_validate_json(raw)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {"msg": str(exc)}
            raise StructuredOutputError(
                f"response does not match {schema.__name__}: {first.get('msg')}", raw, usage
            ) from exc
        return Completion(parsed=parsed, raw=raw, usage=usage)

    async def embed(self, texts: Sequence[str], model: str | None = None) -> list[list[float]]:
        try:
            response = await self._client.embed(
                model=model or self._embedding_model, input=list(texts), keep_alive=self._keep_alive
            )
        except ollama.ResponseError as exc:
            raise LLMError(f"ollama error ({exc.status_code}): {exc.error}") from exc
        except (httpx.HTTPError, ConnectionError) as exc:  # the client maps ConnectError
            raise LLMError(f"ollama unreachable: {type(exc).__name__}") from exc
        return [list(vector) for vector in response.embeddings]
