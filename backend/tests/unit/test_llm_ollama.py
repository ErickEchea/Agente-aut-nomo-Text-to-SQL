import json

import httpx
import pytest
from pydantic import BaseModel

from nexus.llm import GenerationOptions, LLMError, Message, StructuredOutputError
from nexus.llm.ollama import OllamaProvider


class Answer(BaseModel):
    sql: str
    confidence: float


def provider(handler: object) -> OllamaProvider:
    return OllamaProvider(
        "http://ollama:11434",
        "qwen2.5-coder:7b",
        "qwen3-embedding:0.6b",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


def chat_reply(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "qwen2.5-coder:7b",
            "created_at": "2026-11-20T00:00:00Z",
            "message": {"role": "assistant", "content": content},
            "done": True,
            "prompt_eval_count": 120,
            "eval_count": 30,
        },
    )


async def test_complete_sends_schema_and_deterministic_options() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return chat_reply('{"sql": "SELECT 1", "confidence": 0.9}')

    result = await provider(handler).complete(
        [Message("system", "s"), Message("user", "u")], Answer, GenerationOptions(seed=11)
    )
    assert result.parsed == Answer(sql="SELECT 1", confidence=0.9)
    assert result.usage.prompt_tokens == 120
    assert result.usage.total_tokens == 150
    assert seen["model"] == "qwen2.5-coder:7b"
    assert seen["format"] == Answer.model_json_schema()
    assert seen["options"] == {"temperature": 0.0, "seed": 11, "num_ctx": 8192, "num_predict": 1024}
    assert "think" not in seen
    assert seen["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]


async def test_think_and_model_override_are_forwarded() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return chat_reply('{"sql": "SELECT 1", "confidence": 1}')

    await provider(handler).complete(
        [Message("user", "u")], Answer, GenerationOptions(model="qwen3:8b", think=False)
    )
    assert seen["model"] == "qwen3:8b"
    assert seen["think"] is False


async def test_invalid_json_raises_structured_output_error_with_raw_text() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return chat_reply('{"sql": "SELECT 1"}')

    with pytest.raises(StructuredOutputError) as exc_info:
        await provider(handler).complete([Message("user", "u")], Answer)
    assert exc_info.value.raw == '{"sql": "SELECT 1"}'
    assert exc_info.value.usage.completion_tokens == 30


async def test_server_errors_become_llm_errors() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'x' not found"})

    with pytest.raises(LLMError, match="not found"):
        await provider(handler).complete([Message("user", "u")], Answer)


async def test_unreachable_server_becomes_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMError, match="unreachable"):
        await provider(handler).complete([Message("user", "u")], Answer)


async def test_embed_returns_vectors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "qwen3-embedding:0.6b"
        assert body["input"] == ["a", "b"]
        return httpx.Response(
            200, json={"model": body["model"], "embeddings": [[0.1, 0.2], [0.3, 0.4]]}
        )

    assert await provider(handler).embed(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]
