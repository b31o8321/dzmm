"""局域网模型服务发现：目录拉取 + 子网扫描（可注入探针的确定性测试）。"""

import httpx
import pytest


@pytest.mark.anyio
async def test_fetch_remote_models_ollama_and_openai() -> None:
    from dzmm import model_discovery

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}, {"name": "llama3:8b"}]})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen3-14b"}]})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    original_client = model_discovery.httpx.AsyncClient

    class _Client(original_client):  # type: ignore[valid-type,misc]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    model_discovery.httpx.AsyncClient = _Client
    try:
        ollama_models = await model_discovery.fetch_remote_models("ollama", "http://192.168.199.5:11434")
        assert ollama_models == ["qwen2.5:7b", "llama3:8b"]
        openai_models = await model_discovery.fetch_remote_models(
            "lm_studio", "http://192.168.199.5:1234"
        )
        assert openai_models == ["qwen3-14b"]
    finally:
        model_discovery.httpx.AsyncClient = original_client


@pytest.mark.anyio
async def test_scan_lan_classifies_and_normalizes() -> None:
    from dzmm import model_discovery
    from dzmm.model_discovery import DiscoveredServer

    async def fake_classify(host: str, port: int, timeout: float):
        if host == "192.168.199.9" and port == 11434:
            return DiscoveredServer(
                host=host, port=port, provider_hint="ollama",
                base_url="http://192.168.199.9:11434", models=["qwen2.5:7b"],
            )
        if host == "192.168.199.20" and port == 1234:
            return DiscoveredServer(
                host=host, port=port, provider_hint="lm_studio",
                base_url="http://192.168.199.20:1234/v1", models=["qwen3-14b"],
            )
        return None

    results = await model_discovery.scan_lan(subnet="192.168.199", prober=fake_classify)
    assert {item["provider_hint"] for item in results} == {"ollama", "lm_studio"}
    by_hint = {item["provider_hint"]: item for item in results}
    assert by_hint["ollama"]["models"] == ["qwen2.5:7b"]
    assert by_hint["lm_studio"]["base_url"].endswith("/v1")


@pytest.mark.anyio
async def test_scan_lan_survives_unreachable_subnet() -> None:
    from dzmm import model_discovery

    async def unreachable(host: str, port: int, timeout: float):
        raise OSError("no route")

    results = await model_discovery.scan_lan(subnet="10.255.255", prober=unreachable)
    assert results == []
