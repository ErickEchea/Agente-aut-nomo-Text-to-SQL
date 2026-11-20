import asyncio

import httpx
from fastapi.testclient import TestClient

from nexus.config import Settings
from nexus.health.checks import CheckFailedError, OllamaCheck, run_check, run_checks
from nexus.main import create_app


class StaticCheck:
    def __init__(self, name: str, *, fail: Exception | None = None, delay: float = 0.0) -> None:
        self.name = name
        self._fail = fail
        self._delay = delay

    async def probe(self) -> dict[str, object]:
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail:
            raise self._fail
        return {"probe": self.name}


def _settings() -> Settings:
    db = {"host": "h", "name": "n", "user": "u", "password": "p"}
    return Settings(
        app_db=db,
        demo_db=db,
        security={"jwt_secret": "x" * 32},
        cors_origins=["http://localhost:8080"],
        log_json=True,
    )  # type: ignore[arg-type]


def test_live_endpoint() -> None:
    app = create_app(_settings(), health_checks=[])
    with TestClient(app) as client:
        response = client.get("/api/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_ready_when_all_checks_pass() -> None:
    app = create_app(_settings(), health_checks=[StaticCheck("app_db"), StaticCheck("ollama")])
    with TestClient(app) as client:
        response = client.get("/api/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["app_db"] == {
        "ok": True,
        "latency_ms": body["checks"]["app_db"]["latency_ms"],
        "detail": {"probe": "app_db"},
    }


def test_not_ready_reports_each_failure_without_hiding_others() -> None:
    checks = [
        StaticCheck("app_db"),
        StaticCheck("demo_db", fail=CheckFailedError("not read-only", {"read_only": False})),
        StaticCheck("ollama", fail=ConnectionError("refused")),
    ]
    app = create_app(_settings(), health_checks=checks)
    with TestClient(app) as client:
        response = client.get("/api/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["app_db"]["ok"] is True
    assert body["checks"]["demo_db"]["detail"] == {"error": "not read-only", "read_only": False}
    assert body["checks"]["ollama"]["detail"]["error"] == "ConnectionError"


def test_request_id_is_echoed_or_generated() -> None:
    app = create_app(_settings(), health_checks=[])
    with TestClient(app) as client:
        echoed = client.get("/api/health/live", headers={"X-Request-ID": "trace-42"})
        generated = client.get("/api/health/live", headers={"X-Request-ID": "bad id with spaces"})
    assert echoed.headers["x-request-id"] == "trace-42"
    assert generated.headers["x-request-id"] != "bad id with spaces"
    assert len(generated.headers["x-request-id"]) == 32


def test_cors_allows_only_configured_origins() -> None:
    app = create_app(_settings(), health_checks=[])
    with TestClient(app) as client:
        allowed = client.options(
            "/api/health/live",
            headers={"Origin": "http://localhost:8080", "Access-Control-Request-Method": "GET"},
        )
        denied = client.options(
            "/api/health/live",
            headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
        )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:8080"
    assert "access-control-allow-origin" not in denied.headers


async def test_run_check_times_out() -> None:
    result = await run_check(StaticCheck("slow", delay=1.0), timeout_s=0.05)
    assert result.ok is False
    assert "timed out" in str(result.detail["error"])


async def test_run_checks_runs_concurrently() -> None:
    results = await run_checks([StaticCheck("a", delay=0.2), StaticCheck("b", delay=0.2)], 1.0)
    assert [r.ok for r in results] == [True, True]
    assert max(r.latency_ms for r in results) < 390


def _ollama_client(models: list[str], status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(status, json={"models": [{"name": m} for m in models]})

    return httpx.AsyncClient(base_url="http://ollama:11434", transport=httpx.MockTransport(handler))


async def test_ollama_check_passes_when_models_present() -> None:
    async with _ollama_client(["qwen2.5-coder:7b", "qwen3-embedding:0.6b", "other:1b"]) as client:
        check = OllamaCheck(client, ["qwen2.5-coder:7b", "qwen3-embedding:0.6b"])
        result = await run_check(check, 1.0)
    assert result.ok
    assert result.detail["missing"] == []


async def test_ollama_check_lists_missing_models() -> None:
    async with _ollama_client(["qwen3-embedding:0.6b"]) as client:
        result = await run_check(
            OllamaCheck(client, ["qwen2.5-coder:7b", "qwen3-embedding:0.6b"]), 1.0
        )
    assert not result.ok
    assert result.detail["missing"] == ["qwen2.5-coder:7b"]


async def test_ollama_check_reports_http_errors() -> None:
    async with _ollama_client([], status=500) as client:
        result = await run_check(OllamaCheck(client, ["m"]), 1.0)
    assert not result.ok
    assert result.detail["error"] == "HTTPStatusError"
