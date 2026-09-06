import json
import urllib.error

import pytest

from dzmm import embedded_model_requests
from dzmm.core_runtime_errors import CoreRuntimeError
from dzmm.embedded_model_requests import (
    clean_model_narrative,
    request_narrative,
    request_world_draft,
    strip_json_fence,
)


class _Response:
    def __init__(self, body: dict) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._body).encode()


def _capture_request(monkeypatch, response: dict | None = None):
    captured = {}

    def open_request(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response(response or {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(embedded_model_requests.urllib.request, "urlopen", open_request)
    return captured


def test_narrative_request_disables_qwen_thinking_and_uses_openai_endpoint(monkeypatch) -> None:
    captured = _capture_request(monkeypatch)
    request_narrative(
        {
            "provider_type": "lm_studio",
            "base_url": "http://127.0.0.1:1234/v1",
            "model_name": "qwen3-30b",
        },
        {"player_input": "查看灯号"},
    )

    assert captured["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    assert captured["timeout"] == 120
    assert captured["payload"]["max_tokens"] == 480
    assert captured["payload"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert captured["payload"]["messages"][1]["content"].startswith("/no_think\n")
    assert (
        "不得输出 JSON、标签、Markdown 标题、列表或状态摘要"
        in captured["payload"]["messages"][0]["content"]
    )


def test_world_draft_request_keeps_json_schema_at_the_model_boundary(monkeypatch) -> None:
    captured = _capture_request(monkeypatch)
    request_world_draft(
        {
            "provider_type": "lm_studio",
            "base_url": "http://127.0.0.1:1234/v1",
            "model_name": "local-author",
        },
        {"genre": "潮汐悬疑"},
    )

    response_format = captured["payload"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"]["required"] == [
        "world_definition",
        "hero",
    ]


def test_model_protocol_error_is_not_accepted_as_empty_success(monkeypatch) -> None:
    _capture_request(monkeypatch, {"error": "model not loaded"})

    with pytest.raises(CoreRuntimeError, match="model protocol error: model not loaded"):
        request_narrative(
            {
                "provider_type": "ollama",
                "base_url": "http://127.0.0.1:11434",
                "model_name": "qwen3:8b",
            },
            {"player_input": "前进"},
        )


def test_embedded_model_timeout_explains_safety_and_recovery(monkeypatch) -> None:
    def time_out(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(embedded_model_requests.urllib.request, "urlopen", time_out)

    with pytest.raises(
        CoreRuntimeError,
        match="模型在 120 秒内没有返回内容.*没有写入结果.*重试",
    ):
        request_narrative(
            {
                "provider_type": "ollama",
                "base_url": "http://127.0.0.1:11434",
                "model_name": "qwen3:8b",
            },
            {"player_input": "前进"},
        )


def test_embedded_model_connection_failure_hides_transport_exception(monkeypatch) -> None:
    def fail_to_connect(*_args, **_kwargs):
        raise urllib.error.URLError(ConnectionRefusedError("connection refused"))

    monkeypatch.setattr(embedded_model_requests.urllib.request, "urlopen", fail_to_connect)

    with pytest.raises(CoreRuntimeError) as captured:
        request_narrative(
            {
                "provider_type": "ollama",
                "base_url": "http://127.0.0.1:11434",
                "model_name": "qwen3:8b",
            },
            {"player_input": "前进"},
        )

    assert str(captured.value).startswith("无法连接模型服务。")
    assert "connection refused" not in str(captured.value)


def test_model_output_cleanup_removes_thinking_and_json_fences() -> None:
    assert clean_model_narrative("<think>secret</think>港口重新亮起。") == "港口重新亮起。"
    assert clean_model_narrative("<think>unfinished") == ""
    assert (
        clean_model_narrative(
            "潮门在雾中打开。\n\n状态摘要： - 当前章节：第二章 - 主角：旅人 - 目的地：海港"
        )
        == "潮门在雾中打开。"
    )
    assert (
        clean_model_narrative("岚牵着旅人走入雾中。\n\n此时游戏系统锁定了“前往潮门”路线。")
        == "岚牵着旅人走入雾中。"
    )
    assert strip_json_fence('```json\n{"world_definition":{}}\n```') == ('{"world_definition":{}}')
