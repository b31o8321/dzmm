"""Tests for dzmm.eval.export — Phase D JSONL training-data exporter."""
from __future__ import annotations

import json
import pytest

from dzmm.eval.judge_agent import EvalScore
from dzmm.eval.export import export_jsonl


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_score(turn: int, overall_overall: float, session_id: int = 1) -> EvalScore:
    """Build an EvalScore whose .overall == overall_overall.

    overall = (plot_speed + (10 - violations*2) + rp_immersion + dice_accuracy) / 4
    Simplest path: violations=0, set all three dims to overall_overall.
    That gives overall = (x + 10 + x + x) / 4.  Solve for x:
      4*target = 3x + 10  →  x = (4*target - 10) / 3
    """
    target = overall_overall
    x = (4 * target - 10) / 3
    return EvalScore(
        session_id=session_id,
        turn=turn,
        config_name="test_cfg",
        plot_speed=x,
        rule_violations=0,
        rp_immersion=x,
        dice_accuracy=x,
        reasoning="test reasoning",
    )


def _make_prompt_json(content: str = "user msg") -> str:
    """Return a minimal prompt_json list as a JSON string."""
    return json.dumps([{"role": "user", "content": content}])


class _FakeMessage:
    """Minimal stand-in for dzmm.db.models.Message."""

    def __init__(
        self,
        session_id: int,
        turn: int,
        content: str = "GM reply",
        prompt_json: str = "",
        role: str = "assistant",
    ):
        self.session_id = session_id
        self.turn = turn
        self.content = content
        self.prompt_json = prompt_json
        self.role = role


class _FakeScalarsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self


class _FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalarsResult(self._rows)


class _FakeDB:
    """Minimal async DB session stub."""

    def __init__(self, messages: list[_FakeMessage]):
        self._messages = messages

    async def execute(self, stmt):  # noqa: ARG002
        return _FakeExecuteResult(self._messages)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _make_session_maker(messages: list[_FakeMessage]):
    def session_maker():
        return _FakeDB(messages)
    return session_maker


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_writes_records_above_threshold(tmp_path):
    """Only turns with overall >= min_overall should be written."""
    scores = [
        _make_score(turn=1, overall_overall=8.0),   # above threshold → written
        _make_score(turn=2, overall_overall=6.0),   # below threshold → skipped
        _make_score(turn=3, overall_overall=9.0),   # above threshold → written
    ]
    messages = [
        _FakeMessage(session_id=1, turn=1, prompt_json=_make_prompt_json("msg1")),
        _FakeMessage(session_id=1, turn=2, prompt_json=_make_prompt_json("msg2")),
        _FakeMessage(session_id=1, turn=3, prompt_json=_make_prompt_json("msg3")),
    ]
    out = tmp_path / "out.jsonl"
    count = await export_jsonl(1, scores, out, _make_session_maker(messages), min_overall=7.0)

    assert count == 2
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    turns_written = {json.loads(line)["turn"] for line in lines}
    assert turns_written == {1, 3}


@pytest.mark.asyncio
async def test_export_skips_messages_without_prompt_json(tmp_path, capsys):
    """Rows with empty prompt_json are skipped; a summary warning is printed."""
    scores = [
        _make_score(turn=1, overall_overall=8.0),
        _make_score(turn=2, overall_overall=9.0),
    ]
    messages = [
        _FakeMessage(session_id=1, turn=1, prompt_json=""),          # empty → skip
        _FakeMessage(session_id=1, turn=2, prompt_json=_make_prompt_json()),  # has data
    ]
    out = tmp_path / "out.jsonl"
    count = await export_jsonl(1, scores, out, _make_session_maker(messages), min_overall=7.0)

    assert count == 1
    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert "1 turns had no prompt_json" in captured.out


@pytest.mark.asyncio
async def test_export_jsonl_structure(tmp_path):
    """Every output line must be valid JSON with all required keys."""
    scores = [_make_score(turn=1, overall_overall=8.0)]
    prompt = [{"role": "system", "content": "you are a GM"}, {"role": "user", "content": "hello"}]
    messages = [
        _FakeMessage(
            session_id=1,
            turn=1,
            content="<narration>You enter the room.</narration>",
            prompt_json=json.dumps(prompt),
        )
    ]
    out = tmp_path / "out.jsonl"
    count = await export_jsonl(1, scores, out, _make_session_maker(messages), min_overall=7.0)

    assert count == 1
    record = json.loads(out.read_text(encoding="utf-8").strip())

    # Top-level required keys
    for key in ("session_id", "turn", "config_name", "messages", "completion", "score"):
        assert key in record, f"missing key: {key}"

    # messages must be a list of {role, content}
    assert isinstance(record["messages"], list)
    assert len(record["messages"]) == 2
    for m in record["messages"]:
        assert "role" in m
        assert "content" in m

    # score sub-object keys
    for key in ("plot_speed", "rule_violations", "rp_immersion", "dice_accuracy", "overall", "reasoning"):
        assert key in record["score"], f"missing score key: {key}"

    assert record["completion"] == "<narration>You enter the room.</narration>"
    assert record["session_id"] == 1
    assert record["turn"] == 1


@pytest.mark.asyncio
async def test_export_unicode_preservation(tmp_path):
    """Non-ASCII (Chinese) content must survive a JSON round-trip."""
    chinese_content = "你走进了一间昏暗的酒馆，角落里有几个神秘的旅客。"
    chinese_prompt = "你的角色叫林峰，一名侦探。"
    scores = [_make_score(turn=5, overall_overall=8.5)]
    messages = [
        _FakeMessage(
            session_id=1,
            turn=5,
            content=chinese_content,
            prompt_json=json.dumps([{"role": "user", "content": chinese_prompt}]),
        )
    ]
    out = tmp_path / "unicode.jsonl"
    count = await export_jsonl(1, scores, out, _make_session_maker(messages), min_overall=7.0)

    assert count == 1
    raw = out.read_text(encoding="utf-8")
    record = json.loads(raw)

    assert record["completion"] == chinese_content
    assert record["messages"][0]["content"] == chinese_prompt
    # Verify Chinese characters are stored literally (not as \uXXXX escapes)
    assert chinese_content in raw
    assert chinese_prompt in raw
