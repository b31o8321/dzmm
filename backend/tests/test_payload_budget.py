"""Payload budget: the GM payload keeps bounded narrative memory."""

from __future__ import annotations

from dzmm.model_profiles import _narrative_memory_payload


def _state_with_recent_turns(turn_count: int, narrative_len: int = 600) -> dict:
    turns = [
        {
            "turn": index,
            "player_input": "行动" * 300,
            "narrative": "叙事" * narrative_len,
            "outcomes": [{"type": f"o{index}-{i}", "extra": "x" * 400} for i in range(8)],
            "dialogues": [
                {"speaker": "看门人" * 10, "text": "台词" * 200} for _ in range(6)
            ],
        }
        for index in range(turn_count)
    ]
    return {"narrative_context": {"recent_turns": turns}}


def test_keeps_only_recent_turns_and_trims_texts() -> None:
    payload = _narrative_memory_payload(_state_with_recent_turns(8))
    assert [item["turn"] for item in payload] == [4, 5, 6, 7]
    for item in payload:
        assert len(item["narrative"]) <= 240
        assert len(item["player_input"]) <= 200
        assert len(item["dialogues"]) <= 4
        for dialogue in item["dialogues"]:
            assert len(dialogue["text"]) <= 120
            assert len(dialogue["speaker"]) <= 40
        assert len(item["outcomes"]) <= 6
        for outcome in item["outcomes"]:
            assert set(outcome) == {"type"}


def test_total_memory_size_is_bounded() -> None:
    payload = _narrative_memory_payload(_state_with_recent_turns(8))
    total = sum(
        len(item["narrative"]) + len(item["player_input"])
        + sum(len(d["text"]) for d in item["dialogues"])
        for item in payload
    )
    # 4 turns × (240 narrative + 200 input + 4×120 dialogue) ≈ 3.3k 字上限
    assert total < 4000


def test_empty_and_malformed_states_are_safe() -> None:
    assert _narrative_memory_payload({}) == []
    assert _narrative_memory_payload({"narrative_context": None}) == []
    assert _narrative_memory_payload({"narrative_context": {"recent_turns": ["bad", 3]}}) == []
