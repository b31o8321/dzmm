"""Tests for GET /model_configs/{cfg_id}/check endpoint."""
import pytest
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.main import create_app


@pytest.fixture
async def app(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    engine = get_engine(db_url)
    await init_db(engine)
    session_maker = async_session(engine)
    app = create_app(session_maker)
    app.state.session_maker = session_maker
    yield app
    await engine.dispose()


@pytest.fixture
async def http(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _create_ollama_config(http, model_name="qwen2.5:7b"):
    r = await http.post("/model_configs", json={
        "name": "local-ollama",
        "type": "ollama",
        "base_url": "http://localhost:11434",
        "model_name": model_name,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _create_openai_config(http):
    r = await http.post("/model_configs", json={
        "name": "remote-openai",
        "type": "openai_compat",
        "base_url": "https://api.example.com/v1",
        "model_name": "gpt-4o",
        "api_key": "sk-fake",
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def test_check_returns_both_ok_when_models_present(http):
    """When both narrative model and nomic-embed-text are in Ollama, returns ok."""
    cfg_id = await _create_ollama_config(http, model_name="qwen2.5:7b")

    mock_client = AsyncMock()
    mock_client.list_models = AsyncMock(return_value=["qwen2.5:7b", "nomic-embed-text:latest"])

    with patch("dzmm.api.routes_models.build_client", return_value=mock_client):
        r = await http.get(f"/model_configs/{cfg_id}/check")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["narrative_ok"] is True
    assert body["embed_ok"] is True
    assert body["missing"] == []


async def test_check_reports_missing_embed_model(http):
    """When only narrative model is present, embed_ok=False and missing includes nomic-embed-text."""
    cfg_id = await _create_ollama_config(http, model_name="qwen2.5:7b")

    mock_client = AsyncMock()
    mock_client.list_models = AsyncMock(return_value=["qwen2.5:7b"])

    with patch("dzmm.api.routes_models.build_client", return_value=mock_client):
        r = await http.get(f"/model_configs/{cfg_id}/check")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["narrative_ok"] is True
    assert body["embed_ok"] is False
    assert "nomic-embed-text" in body["missing"]
    assert "qwen2.5:7b" not in body["missing"]


async def test_check_reports_missing_narrative_model(http):
    """When model_name not in list, narrative_ok=False."""
    cfg_id = await _create_ollama_config(http, model_name="qwen2.5:7b")

    mock_client = AsyncMock()
    mock_client.list_models = AsyncMock(return_value=["nomic-embed-text:latest"])

    with patch("dzmm.api.routes_models.build_client", return_value=mock_client):
        r = await http.get(f"/model_configs/{cfg_id}/check")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["narrative_ok"] is False
    assert body["embed_ok"] is True
    assert "qwen2.5:7b" in body["missing"]
    assert "nomic-embed-text" not in body["missing"]


async def test_check_non_ollama_returns_null_embed(http):
    """For openai_compat type, embed_ok=null (not applicable)."""
    cfg_id = await _create_openai_config(http)

    mock_client = AsyncMock()
    mock_client.health_check = AsyncMock(return_value=(True, "ok"))

    with patch("dzmm.api.routes_models.build_client", return_value=mock_client):
        r = await http.get(f"/model_configs/{cfg_id}/check")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["narrative_ok"] is True
    assert body["embed_ok"] is None
    assert body["missing"] == []
