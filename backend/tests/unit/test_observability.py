import json
import logging

import pytest
import structlog

from nexus.observability.logging import REDACTED, configure_logging, redact_secrets
from nexus.observability.middleware import resolve_request_id


def test_redact_secrets_masks_sensitive_keys_recursively() -> None:
    event = {
        "event": "x",
        "password": "p",
        "db": {"user": "u", "DB_PASSWORD": "p2", "nested": {"api_key": "k"}},
        "Authorization": "Bearer t",
        "rows": 3,
    }
    out = redact_secrets(None, "info", event)
    assert out["password"] == REDACTED
    assert out["db"]["DB_PASSWORD"] == REDACTED
    assert out["db"]["nested"]["api_key"] == REDACTED
    assert out["Authorization"] == REDACTED
    assert out["db"]["user"] == "u"
    assert out["rows"] == 3


def test_json_logs_carry_bound_context(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json=True)
    structlog.contextvars.bind_contextvars(request_id="abc123")
    try:
        structlog.get_logger("test").info("hello", password="should-not-appear")
        logging.getLogger("stdlib").warning("from stdlib")
    finally:
        structlog.contextvars.clear_contextvars()

    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    hello = next(line for line in lines if line["event"] == "hello")
    assert hello["request_id"] == "abc123"
    assert hello["password"] == REDACTED
    assert hello["level"] == "info"
    assert "timestamp" in hello
    assert any(line["event"] == "from stdlib" for line in lines)


@pytest.mark.parametrize(
    ("incoming", "keeps"),
    [
        ("abc-123_DEF.9", True),
        ("x" * 64, True),
        ("x" * 65, False),
        ("has space", False),
        ("inject\nnewline", False),
        ("", False),
        (None, False),
    ],
)
def test_resolve_request_id(incoming: str | None, keeps: bool) -> None:
    resolved = resolve_request_id(incoming)
    if keeps:
        assert resolved == incoming
    else:
        assert resolved != incoming
        assert len(resolved) == 32
