"""嵌入式通道端到端冒烟：LocalCoreRuntime + 真实 Ollama（与手机 App 完全同链路）。

为什么存在：backend 的 HTTP 层测试与手机 App 实际运行的嵌入式运行时是两条
实现路径。真机上「扫描崩溃 / 草案截断 / 英文输出 / 4096 上下文」四连缺陷
全部位于本文件覆盖的层级——此前该层级零测试。需要本机 Ollama 在线；无
Ollama 时整文件跳过（CI 环境安全），本地开发必须随 backend 全量一起跑。
"""

import json
import urllib.request

import pytest

pytestmark = [
    pytest.mark.skipif(
        _ollama_down := (
            lambda: (lambda r: r.status != 200)(
                urllib.request.urlopen("http://localhost:11434/api/version", timeout=2)
            )
        )(),
        reason="本机 Ollama 不可达",
    )
]


def _profile(rt) -> str:
    with rt._connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO local_model_profiles (id, name, provider_type, base_url, model_name, has_api_key, is_default)"
            " VALUES ('e2e-p', 'e2e-ollama', 'ollama', 'http://localhost:11434', ?, 0, 1)",
            ("qwen2.5:7b",),
        )
    return "e2e-p"


def _runtime(tmp_path):
    from dzmm.core_runtime import LocalCoreRuntime

    return LocalCoreRuntime(tmp_path / "dzmm-v3.db")


def test_embedded_draft_returns_valid_chinese_world(tmp_path) -> None:
    """草案链路端到端：必须产出合法中文世界（拦截截断/英文/结构漂移回归）。"""

    rt = _runtime(tmp_path)
    model = _profile(rt)

    _orig_loads = json.loads

    def _capture_raw(s, *a, **k):
        if isinstance(s, str) and len(s) > 200:
            (tmp_path / "raw_draft.json").write_text(s, encoding="utf-8")
        return _orig_loads(s, *a, **k)

    json.loads = _capture_raw
    try:
        result = rt.generate_draft(
            {
                "model_profile_id": model,
                "genre": "夜市妖怪侦探社",
                "tone": "市井、狡黠",
                "core_conflict": "妖怪们排队来委托寻找丢失的名字。",
                "hero_preference": "能看见妖怪尾巴的人类侦探",
                "ruleset": "hybrid",
            }
        )
    finally:
        json.loads = _orig_loads
    assert result["valid"] is True, result.get("issues")
    definition = result["world_definition"]
    assert definition.get("name")
    assert definition.get("schema_version") == 3
    chinese = sum(
        1
        for ch in (definition.get("name") or "") + str(definition.get("story"))
        if "\u4e00" <= ch <= "\u9fff"
    )
    assert chinese >= 20, f"草案疑似非中文输出：{definition.get('name')!r}"


def test_embedded_probe_and_play_turn_carries_num_ctx(tmp_path) -> None:
    """探针/回合请求必须带 num_ctx（Ollama 默认 4096 是长会话劣化根因）。"""

    rt = _runtime(tmp_path)
    model = _profile(rt)
    result = rt.probe_model_profile("e2e-p")
    assert result["success"] is True, result["detail"]

    with urllib.request.urlopen("http://localhost:11434/api/ps", timeout=5) as response:
        loaded = json.loads(response.read().decode())["models"]
    contexts = {m["name"]: m.get("context_length") for m in loaded}
    assert contexts.get("qwen2.5:7b") == 16384, f"探针后模型上下文={contexts}，应为 16384"

    draft = rt.generate_draft(
        {
            "model_profile_id": "e2e-p",
            "genre": "夜市妖怪侦探社",
            "tone": "市井",
            "core_conflict": "名字失窃案。",
            "hero_preference": "人类侦探",
            "ruleset": "hybrid",
        }
    )
    assert draft["valid"] is True
    world_version = draft["world_definition"]
    world = rt.compose(
        {"request_id": "e2e-world", "world_definition": world_version, "hero": draft["hero"]}
    )
    run = rt.create_run(world["world_id"], {"request_id": "e2e-run", "hero": draft["hero"]})
    snapshot = rt.get_run(run["run_id"])
    turn = rt.play(
        run["run_id"],
        {
            "request_id": "e2e-turn-1",
            "expected_revision": snapshot["state"]["revision"],
            "player_input": "我走进夜市开始调查。",
            "commands": [{"type": "narrate", "payload": {}}],
        },
    )
    assert turn.get("narrative") or turn.get("story_beats")
    with urllib.request.urlopen("http://localhost:11434/api/ps", timeout=5) as response:
        loaded = json.loads(response.read().decode())["models"]
    assert all(m.get("context_length", 0) >= 16384 for m in loaded), contexts
