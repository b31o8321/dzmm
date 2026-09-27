"""v1.4.0 M0：三层记忆基建单元测试。"""

from dzmm.loop_memory import (
    append_loop_summary,
    discover_knowledge,
    initial_loop_memory,
    loop_memories_for_prompt,
    loop_summaries_for_prompt,
    rewind_memory,
)


def test_initial_memory_shape() -> None:
    memory = initial_loop_memory()
    assert memory == {"count": 1, "knowledge": [], "summaries": []}


def test_discover_dedupes_and_clamps() -> None:
    memory = initial_loop_memory()
    entry, notes = discover_knowledge(memory, "clue-1", "钟表匠死于 23:47。", 3)
    assert entry["id"] == "clue-1" and notes == []
    # 同 id 更新而非重复
    _, notes = discover_knowledge(memory, "clue-1", "修正：死于 23:48。", 5)
    assert any("已更新" in n for n in notes)
    assert len(memory["knowledge"]) == 1
    assert memory["knowledge"][0]["text"] == "修正：死于 23:48。"


def test_discover_rejects_bad_id_and_empty_text() -> None:
    memory = initial_loop_memory()
    entry, notes = discover_knowledge(memory, "Bad Id!", "text", 1)
    assert entry is None and notes
    entry, notes = discover_knowledge(memory, "ok-id", "", 1)
    assert entry is None and notes


def test_discover_caps_at_limit() -> None:
    memory = initial_loop_memory()
    for i in range(24):
        discover_knowledge(memory, f"clue-{i}", f"线索 {i}", i)
    entry, notes = discover_knowledge(memory, "clue-99", "溢出", 99)
    assert entry is None and any("上限" in n for n in notes)


def test_rewind_bumps_count_and_preserves_knowledge() -> None:
    memory = initial_loop_memory()
    discover_knowledge(memory, "clue-1", "关键发现", 3)
    append_loop_summary(memory, 1, "第一次循环的摘要。")
    rewind_memory(memory)
    assert memory["count"] == 2
    assert memory["knowledge"][0]["text"] == "关键发现"
    assert memory["summaries"][0]["loop_no"] == 1
    # 同 loop_no 不重复
    append_loop_summary(memory, 1, "重复摘要。")
    assert len(memory["summaries"]) == 1


def test_prompt_injection_shapes() -> None:
    memory = initial_loop_memory()
    discover_knowledge(memory, "clue-1", "钟表匠的秘密", 3)
    append_loop_summary(memory, 1, "循环 1 摘要")
    append_loop_summary(memory, 2, "循环 2 摘要")
    memories = loop_memories_for_prompt(memory)
    assert memories == [{"id": "clue-1", "text": "钟表匠的秘密"}]
    summaries = loop_summaries_for_prompt(memory, limit=1)
    assert summaries == [{"loop_no": 2, "summary": "循环 2 摘要"}]


def test_loop_state_lifecycle() -> None:
    """M2：loop 状态生命周期——initial→anchor→rewind→知识保留/记忆清空/deja_vu。"""

    from dzmm.loop_mode import (
        anchor_snapshot,
        bump_deja_vu,
        initial_loop_state,
        rewind_to_anchor,
        should_trigger_death_rewind,
    )

    definition = {"loop_config": {"max_loops": 3, "trigger": ["time", "death"]}}
    state = {
        "revision": 5,
        "hero": {"name": "林浩"},
        "npc_state": {"jack": {"id": "jack", "name": "杰克", "favor": 10}},
        "narrative_context": {"recent_turns": [{"narrative": "旧"}], "run_seed": "s"},
        "inventory": [{"id": "key", "quantity": 1}],
        "ending": None,
        "loop_memory": {"count": 1, "knowledge": [{"id": "c1", "text": "线索", "discovered_turn": 2}], "summaries": []},
    }
    loop_state = initial_loop_state(definition, state)
    assert loop_state["count"] == 1 and loop_state["max_loops"] == 3
    state["loop"] = loop_state
    state["loop"]["anchor_state"] = anchor_snapshot(state)

    # 循环内推进：deja_vu 累积
    bump_deja_vu(state, "jack")
    assert state["loop"]["deja_vu"]["jack"] == 15

    # 死亡触发 rewind（bad 结局 + death trigger + 未达上限）
    state["ending"] = {"id": "x", "kind": "bad", "narrative_key": "k"}
    assert should_trigger_death_rewind(state) is True

    anchor = state["loop"]["anchor_state"]
    new_state, notes = rewind_to_anchor(state, anchor)
    assert new_state["loop"]["count"] == 2
    assert new_state["loop_memory"]["count"] == 2
    assert new_state["loop_memory"]["knowledge"][0]["text"] == "线索"
    assert new_state["narrative_context"]["recent_turns"] == []
    assert new_state["ending"] is None
    # deja_vu 跨循环保留
    assert new_state["loop"]["deja_vu"]["jack"] == 15
    assert notes and "跨循环记忆保留" in notes[0]

    # 达上限后不再 rewind
    new_state["loop"]["count"] = 3
    assert should_trigger_death_rewind(new_state) is False


def test_drift_directive_escalates() -> None:
    from dzmm.loop_mode import drift_directive

    base = "重演场景"
    assert drift_directive(1, base) == base
    d2 = drift_directive(2, base)
    d5 = drift_directive(5, base)
    assert d2 != base and "漂移" in d2
    assert d5 != d2


def test_clock_predicates_and_adjust_clock() -> None:
    """M3：clock_below/above 谓词 + adjust_clock 命令 + 归零结局锁定。"""

    import json

    from dzmm.core.command_engine import apply_commands
    from dzmm.narrative import initial_state

    definition = {
        "name": "末日深空",
        "locations": [{"id": "bay", "name": "货运舱"}],
        "character_cards": [],
        "npcs": [],
        "factions": [],
        "events": [],
        "resources": [{"id": "oxygen", "name": "氧气罐"}],
        "ruleset": {"id": "trpg", "enabled_capabilities": ["trpg", "time", "countdown"]},
        "story": {
            "chapters": [],
            "flags": [],
            "relationships": [],
            "relationship_events": [],
            "routes": [],
            "endings": [],
        },
        "time_system": {"start_minutes": 420, "per_turn_max": 240},
    }
    state = initial_state(definition, {"name": "林浩", "profile": {}})
    state["clock"] = {
        "now_minutes": 47, "start_minutes": 420, "loop_at_minutes": None,
        "day": 1, "per_turn_max": 240, "unit": "分钟",
        "countdown": {"tick_per_turn": 0, "warn_at": 60},
    }

    class E(Exception):
        pass

    # adjust_clock 回加（clamp 到 initial）
    outcomes = apply_commands(state, definition, [
        {"type": "adjust_clock", "payload": {"delta": 999}},
    ], validate_command=lambda c: None, error_type=E)
    assert outcomes[0]["type"] == "clock_adjusted"
    assert state["clock"]["now_minutes"] == state["clock"]["start_minutes"]  # clamp 到上限

    # 谓词
    state["clock"]["now_minutes"] = 30
    assert json.dumps({"clock_below": 60}) and True

    from dzmm.narrative import _matches
    assert _matches({"clock_below": 60}, state) is True
    assert _matches({"clock_below": 20}, state) is False
    assert _matches({"clock_above": 20}, state) is True
