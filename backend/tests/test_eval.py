"""Tests for Phase C autonomous evaluation agents."""
import json
import pytest
from dzmm.models.client import GenerationParams, ModelClient, StreamChunk, TokenUsage
from dzmm.prompts.player_template import build_player_messages
from dzmm.prompts.judge_template import build_judge_messages


class _FakeClient(ModelClient):
    name = "fake"

    def __init__(self, response: str):
        self._response = response

    async def stream(self, messages, params):  # noqa: ARG002
        yield StreamChunk(delta=self._response, finish_reason="stop")

    async def complete(self, messages, params):  # noqa: ARG002
        return self._response, TokenUsage()


def test_build_player_messages_includes_history():
    msgs = build_player_messages(
        character_name="林峰",
        character_md="林峰，一名侦探，沉默寡言。",
        recent_history=[("我走进房间", "你看到一具尸体倒在地板上，窗户半开。")],
    )
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert "林峰" in msgs[0].content
    assert "尸体" in msgs[0].content


def test_build_judge_messages_includes_history():
    msgs = build_judge_messages(
        world_summary="维多利亚时代的伦敦，充满迷雾和阴谋。",
        recent_history=[("我检查现场", "你发现了一枚奇怪的徽章。")],
        n_turns=1,
    )
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert "维多利亚" in msgs[0].content
    assert "plot_speed" in msgs[0].content


from dzmm.eval.player_agent import generate_player_action
from dzmm.eval.judge_agent import EvalScore, judge_session


def _fake_message(role: str, content: str, turn: int = 1):
    """Build a minimal stub that mimics Message ORM fields we need."""
    class _Msg:
        pass
    m = _Msg()
    m.role = role
    m.content = content
    m.turn = turn
    return m


@pytest.mark.asyncio
async def test_generate_player_action_returns_nonempty_string():
    client = _FakeClient("我小心翼翼地推开门，走进了房间。")
    msgs = [
        _fake_message("user", "我走进酒馆"),
        _fake_message("assistant", "你看到一个昏暗的大厅，几个陌生人坐在角落。"),
    ]
    action = await generate_player_action(
        messages=msgs,
        character_md="林峰，侦探，谨慎。",
        character_name="林峰",
        client=client,
    )
    assert isinstance(action, str)
    assert len(action) > 0
    assert "推开门" in action


@pytest.mark.asyncio
async def test_judge_session_parses_valid_json():
    valid_json = json.dumps({
        "plot_speed": 7,
        "rule_violations": 1,
        "rp_immersion": 8,
        "dice_accuracy": 9,
        "reasoning": "剧情推进顺畅。",
    })
    client = _FakeClient(valid_json)
    msgs = [
        _fake_message("user", "我检查现场", turn=1),
        _fake_message("assistant", "你发现了一枚徽章。", turn=1),
    ]
    score = await judge_session(
        messages=msgs,
        world_summary="维多利亚伦敦",
        session_id=1,
        turn=10,
        config_name="single_gm",
        client=client,
    )
    assert isinstance(score, EvalScore)
    assert score.plot_speed == 7
    assert score.rule_violations == 1
    assert score.rp_immersion == 8
    assert score.dice_accuracy == 9
    assert score.session_id == 1
    assert score.turn == 10
    assert score.config_name == "single_gm"


@pytest.mark.asyncio
async def test_judge_session_handles_malformed_json():
    """judge_session should return a default score (5.0 all dims) on parse failure."""
    client = _FakeClient("这是一个非 JSON 回复，无法解析。")
    msgs = [_fake_message("user", "行动", turn=1)]
    score = await judge_session(
        messages=msgs,
        world_summary="",
        session_id=2,
        turn=5,
        config_name="test",
        client=client,
    )
    assert isinstance(score, EvalScore)
    assert score.plot_speed == 5.0
    assert score.rule_violations == 0
    assert score.reasoning != ""


@pytest.mark.asyncio
async def test_eval_score_overall_property():
    score = EvalScore(
        session_id=1, turn=10, config_name="test",
        plot_speed=8.0, rule_violations=0,
        rp_immersion=7.0, dice_accuracy=9.0,
        reasoning="good",
    )
    # overall = (plot_speed + (10 - violations*2) + rp_immersion + dice_accuracy) / 4
    expected = (8.0 + 10.0 + 7.0 + 9.0) / 4
    assert abs(score.overall - expected) < 0.01
