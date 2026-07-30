"""Tests for Phase C autonomous evaluation agents."""
import json
from unittest.mock import MagicMock, patch

import pytest
from dzmm.eval.judge_agent import EvalScore, judge_session
from dzmm.eval.player_agent import generate_player_action
from dzmm.eval.report import generate_report
from dzmm.eval.runner import EvalConfig, run_eval
from dzmm.models.client import ModelClient, StreamChunk, TokenUsage
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


@pytest.mark.asyncio
async def test_run_eval_runs_correct_number_of_turns():
    """run_eval should call run_turn() once per turn and return one score per judge_every turns."""
    turn_calls = []

    async def fake_run_turn(session, session_id, action, client, **kwargs):
        turn_calls.append((session_id, action))
        return
        yield  # Make it an async generator

    class _FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            pass
        async def get(self, cls, pk):
            if cls.__name__ == "Session":
                m = MagicMock()
                m.world_id = 1
                m.character_id = 1
                m.settings_json = "{}"
                m.gm_model_config_id = None
                return m
            if cls.__name__ == "Character":
                m = MagicMock()
                m.profile_md = "林峰，侦探。"
                m.name = "林峰"
                return m
            if cls.__name__ == "World":
                m = MagicMock()
                m.content_md = "维多利亚伦敦"
                return m
            return MagicMock()
        async def execute(self, stmt):
            m = MagicMock()
            m.scalars.return_value.all.return_value = []
            return m
        def add(self, obj): pass
        async def commit(self): pass

    def fake_session_maker():
        return _FakeSession()

    valid_score_json = json.dumps({
        "plot_speed": 7, "rule_violations": 0,
        "rp_immersion": 8, "dice_accuracy": 9, "reasoning": "good",
    })
    gm_client = _FakeClient("你走进了一个昏暗的房间。")
    player_client = _FakeClient("我检查周围的环境。")
    judge_client = _FakeClient(valid_score_json)

    config = EvalConfig(
        session_id=1,
        config_name="test",
        max_turns=10,
        judge_every=5,
    )

    with patch("dzmm.eval.runner.run_turn", fake_run_turn):
        scores = await run_eval(config, fake_session_maker, gm_client, player_client, judge_client)

    assert len(turn_calls) == 10
    assert len(scores) == 2  # judge runs at turn 5 and turn 10
    assert all(isinstance(s, EvalScore) for s in scores)


def test_generate_report_contains_both_config_names():
    scores_a = [
        EvalScore(1, 10, "single_gm", 7.0, 1, 8.0, 9.0, "good"),
        EvalScore(1, 20, "single_gm", 6.0, 2, 7.0, 8.0, "ok"),
    ]
    scores_b = [
        EvalScore(2, 10, "multi_agent_gm", 8.0, 0, 9.0, 9.0, "excellent"),
        EvalScore(2, 20, "multi_agent_gm", 8.5, 0, 8.5, 9.5, "great"),
    ]
    report = generate_report(scores_a, "single_gm", scores_b, "multi_agent_gm")
    assert "single_gm" in report
    assert "multi_agent_gm" in report
    assert "plot_speed" in report.lower() or "剧情" in report
    assert isinstance(report, str)
    assert len(report) > 100


def test_generate_report_handles_empty_scores():
    report = generate_report([], "config_a", [], "config_b")
    assert isinstance(report, str)
    assert "config_a" in report or "config_b" in report
