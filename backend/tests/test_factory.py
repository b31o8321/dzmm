from unittest.mock import patch

from dzmm.db.models import ModelConfig
from dzmm.models.factory import build_client
from dzmm.models.openai_compat import OpenAICompatClient
from dzmm.models.ollama import OllamaClient


def test_build_openai_compat_client():
    cfg = ModelConfig(
        name="doubao", type="openai_compat",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model_name="ep-xxx", api_key_ref="doubao_main", timeout=30.0,
    )
    with patch("dzmm.models.factory.get_api_key", return_value="sk-fake"):
        c = build_client(cfg)
    assert isinstance(c, OpenAICompatClient)
    assert c.base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert c.model == "ep-xxx"
    assert c.api_key == "sk-fake"
    assert c.timeout == 30.0


def test_build_ollama_client():
    cfg = ModelConfig(
        name="local", type="ollama",
        base_url="http://localhost:11434",
        model_name="qwen2.5:7b", api_key_ref=None, timeout=120.0,
    )
    c = build_client(cfg)
    assert isinstance(c, OllamaClient)
    assert c.model == "qwen2.5:7b"


def test_build_unknown_type_raises():
    cfg = ModelConfig(
        name="x", type="madeup",
        base_url="http://x", model_name="y",
    )
    import pytest
    with pytest.raises(ValueError, match="unknown model type"):
        build_client(cfg)
