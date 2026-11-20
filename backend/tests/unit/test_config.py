import pytest
from pydantic import SecretStr, ValidationError

from nexus.config import DatabaseSettings, Settings


def _db(password: str = "p") -> dict[str, object]:
    return {"host": "db", "name": "n", "user": "u", "password": password}


def test_settings_read_nested_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_APP_DB__HOST", "app-db")
    monkeypatch.setenv("NEXUS_APP_DB__NAME", "nexus_app")
    monkeypatch.setenv("NEXUS_APP_DB__USER", "nexus_app")
    monkeypatch.setenv("NEXUS_APP_DB__PASSWORD", "secret")
    monkeypatch.setenv("NEXUS_DEMO_DB__HOST", "demo-db")
    monkeypatch.setenv("NEXUS_DEMO_DB__NAME", "retail")
    monkeypatch.setenv("NEXUS_DEMO_DB__USER", "nexus_reader")
    monkeypatch.setenv("NEXUS_DEMO_DB__PASSWORD", "secret2")
    monkeypatch.setenv("NEXUS_CORS_ORIGINS", "http://localhost:8080, http://127.0.0.1:8080")
    monkeypatch.setenv("NEXUS_OLLAMA__LLM_MODEL", "qwen3:8b")

    settings = Settings()  # type: ignore[call-arg]

    assert settings.app_db.host == "app-db"
    assert settings.demo_db.user == "nexus_reader"
    assert settings.cors_origins == ["http://localhost:8080", "http://127.0.0.1:8080"]
    assert settings.ollama.required_models == ("qwen3:8b", "qwen3-embedding:0.6b")


def test_missing_database_settings_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("NEXUS_APP_DB__HOST", "NEXUS_DEMO_DB__HOST"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_wildcard_cors_origin_is_rejected() -> None:
    with pytest.raises(ValidationError, match="wildcard"):
        Settings(app_db=_db(), demo_db=_db(), cors_origins=["*"])  # type: ignore[arg-type]


def test_password_is_not_exposed_in_repr() -> None:
    db = DatabaseSettings(host="h", name="n", user="u", password=SecretStr("hunter2"))
    assert "hunter2" not in repr(db)


def test_sqlalchemy_url_escapes_special_characters() -> None:
    db = DatabaseSettings(host="h", port=5433, name="n", user="u", password=SecretStr("p@ss/w:rd"))
    url = db.sqlalchemy_url()
    assert url.password == "p@ss/w:rd"
    assert url.port == 5433
    assert "p%40ss%2Fw%3Ard" in url.render_as_string(hide_password=False)


def test_libpq_conninfo_quotes_values() -> None:
    db = DatabaseSettings(host="h", name="n", user="u", password=SecretStr("it's a \\ secret"))
    conninfo = db.libpq_conninfo()
    assert "password='it\\'s a \\\\ secret'" in conninfo
    assert "connect_timeout='5'" in conninfo
