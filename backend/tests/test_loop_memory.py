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
