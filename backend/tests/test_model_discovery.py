"""局域网模型服务发现：目录拉取 + 子网扫描（可注入探针的确定性测试）。"""

import pytest


@pytest.mark.anyio
async def test_fetch_remote_models_ollama_and_openai(monkeypatch) -> None:
    from dzmm import model_discovery

    seen_urls = []

    def fake_get(url: str, headers: dict, timeout: float):
        seen_urls.append(url)
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen2.5:7b"}, {"name": "llama3:8b"}]}
        if url.endswith("/models"):
            return {"data": [{"id": "qwen3-14b"}]}
        raise OSError("not found")

    monkeypatch.setattr(model_discovery, "_http_get_json", fake_get)
    ollama_models = await model_discovery.fetch_remote_models(
        "ollama", "http://192.168.199.5:11434"
    )
    assert ollama_models == ["qwen2.5:7b", "llama3:8b"]
    openai_models = await model_discovery.fetch_remote_models(
        "lm_studio", "http://192.168.199.5:1234"
    )
    assert openai_models == ["qwen3-14b"]
    assert seen_urls[0].endswith("/api/tags")
    assert seen_urls[1].endswith("/v1/models")


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
