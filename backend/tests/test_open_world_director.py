"""Tests for Plan B: open-world Director agent.

T1 — world_graph BFS
T2 — event scoring + rumor eligibility
T3 — NPC proactive contact
T4 — director prompt messages structure
"""
import json

from dzmm.prompts.director_open_world_template import build_open_world_director_messages
from dzmm.service.agents.director_open_world import (
    check_npc_proactive_contact,
    enrich_plot_directive,
    filter_event_declarations,
    is_rumor_eligible,
    sanitize_open_world_director_output,
    score_event,
)
from dzmm.service.world_graph import build_graph, bfs_distance


def _loc(loc_id: int, connections: list[dict]) -> dict:
    return {"id": loc_id, "connections_json": json.dumps(connections)}


def test_bfs_distance_same_location():
    locs = [_loc(1, [{"target_id": 2, "distance": 1}])]
    graph = build_graph(locs)
    assert bfs_distance(graph, 1, 1) == 0


def test_bfs_distance_adjacent():
    locs = [
        _loc(1, [{"target_id": 2, "distance": 1}]),
        _loc(2, [{"target_id": 1, "distance": 1}]),
    ]
    graph = build_graph(locs)
    assert bfs_distance(graph, 1, 2) == 1


def test_bfs_distance_two_hops():
    locs = [
        _loc(1, [{"target_id": 2, "distance": 1}]),
        _loc(2, [{"target_id": 1, "distance": 1}, {"target_id": 3, "distance": 1}]),
        _loc(3, [{"target_id": 2, "distance": 1}]),
    ]
    graph = build_graph(locs)
    assert bfs_distance(graph, 1, 3) == 2


def test_bfs_distance_unreachable():
    locs = [
        _loc(1, []),
        _loc(2, []),
    ]
    graph = build_graph(locs)
    assert bfs_distance(graph, 1, 2) == 999


# ── T2: event scoring + rumor eligibility ─────────────────────────────────────

def _event(importance: int, scope_ref: str = "1") -> dict:
    return {"id": 1, "importance": importance, "scope_ref": scope_ref,
            "scope_type": "location", "trigger_conditions_json": "[]",
            "is_repeatable": False, "cooldown_turns": 0}


def _npc_state(npc_template_id: int, current_location_id: int | None,
               is_companion: bool = False) -> dict:
    return {"npc_template_id": npc_template_id,
            "current_location_id": current_location_id,
            "is_companion": is_companion}


def test_score_event_at_same_location():
    ev = _event(importance=3, scope_ref="1")
    score = score_event(ev, pc_location_id=1, distance=0,
                        companion_npc_ids=set(), faction_rep_npcs=set())
    assert abs(score - 3.0 * 1.0) < 0.01


def test_score_event_with_companion_bonus():
    ev = {"id": 1, "importance": 3, "scope_ref": "1",
          "scope_type": "npc", "trigger_conditions_json": "[]",
          "is_repeatable": False, "cooldown_turns": 0}
    score = score_event(ev, pc_location_id=1, distance=1,
                        companion_npc_ids={5}, faction_rep_npcs=set(),
                        npc_template_ids_in_event={5})
    # importance(3) * dist_factor(0.8) + companion_bonus(0.3)
    assert abs(score - (3.0 * 0.8 + 0.3)) < 0.01


def test_score_event_dist3_returns_zero():
    ev = _event(importance=5, scope_ref="10")
    score = score_event(ev, pc_location_id=1, distance=3,
                        companion_npc_ids=set(), faction_rep_npcs=set())
    assert score == 0.0


def test_rumor_eligible_far_important():
    ev = _event(importance=3)
    assert is_rumor_eligible(ev, distance=3, delivered=False,
                             turns_since_last=10, cooldown=5) is True


def test_rumor_not_eligible_already_delivered():
    ev = _event(importance=3)
    assert is_rumor_eligible(ev, distance=3, delivered=True,
                             turns_since_last=10, cooldown=5) is False


def test_rumor_not_eligible_on_cooldown():
    ev = _event(importance=3)
    assert is_rumor_eligible(ev, distance=3, delivered=False,
                             turns_since_last=3, cooldown=5) is False


def test_rumor_not_eligible_low_importance():
    ev = _event(importance=2)
    assert is_rumor_eligible(ev, distance=3, delivered=False,
                             turns_since_last=10, cooldown=5) is False


# ── T3: NPC proactive contact ─────────────────────────────────────────────────

def _npc_state_dict(npc_id: int, favor: int, loc_id: int | None,
                    last_contact: int, threshold: int = 70, cooldown: int = 10) -> dict:
    return {
        "npc_template_id": npc_id,
        "favor": favor,
        "current_location_id": loc_id,
        "last_contact_turn": last_contact,
        "contact_favor_threshold": threshold,
        "contact_cooldown_turns": cooldown,
        "is_alive": True,
        "is_companion": False,
    }


def test_npc_contact_eligible():
    npc = _npc_state_dict(1, favor=80, loc_id=2, last_contact=0)
    result = check_npc_proactive_contact(
        npc_states=[npc], pc_location_id=1, current_turn=15
    )
    assert result is not None
    assert result["npc_template_id"] == 1


def test_npc_contact_insufficient_favor():
    npc = _npc_state_dict(1, favor=50, loc_id=2, last_contact=0)
    assert check_npc_proactive_contact([npc], pc_location_id=1, current_turn=15) is None


def test_npc_contact_same_location_skipped():
    # NPC already with PC — no proactive contact needed
    npc = _npc_state_dict(1, favor=90, loc_id=1, last_contact=0)
    assert check_npc_proactive_contact([npc], pc_location_id=1, current_turn=15) is None


def test_npc_contact_on_cooldown():
    npc = _npc_state_dict(1, favor=90, loc_id=2, last_contact=10)
    assert check_npc_proactive_contact([npc], pc_location_id=1, current_turn=15) is None


def test_npc_contact_dead_skipped():
    npc = _npc_state_dict(1, favor=90, loc_id=2, last_contact=0)
    npc["is_alive"] = False
    assert check_npc_proactive_contact([npc], pc_location_id=1, current_turn=15) is None


# ── T4: prompt messages structure ─────────────────────────────────────────────

def test_open_world_director_messages_structure():
    msgs = build_open_world_director_messages(
        history=[],
        snapshot={
            "current_location": "暗影港",
            "pc_summary": "林峰，侦探",
            "companions": [],
            "candidate_events": [
                {
                    "id": 7, "name": "谋杀案", "score": 2.4,
                    "importance": 3, "summary_md": "港口尸体",
                },
            ],
            "rumor_events": [],
            "proactive_npc": None,
            "campaign_phase": None,
            "faction_tensions": [],
        },
    )
    assert msgs[0].role == "system"
    assert msgs[-1].role == "user"
    assert "暗影港" in msgs[-1].content
    assert "谋杀案" in msgs[-1].content
    assert "id=7" in msgs[-1].content


def test_director_output_discards_parallel_story_prose():
    raw = (
        "艾琳娜拿出电脑，继续安装摄像机。\n"
        '<event_trigger event_id="7"/>\n'
        "<plot_directive>\n- 本回合主推：教会异动\n- 禁止：替玩家行动\n</plot_directive>"
    )
    clean = sanitize_open_world_director_output(raw)
    assert "艾琳娜拿出电脑" not in clean
    assert '<event_trigger event_id="7"/>' in clean
    assert "教会异动" in clean


def test_director_output_without_exact_directive_uses_safe_fallback():
    clean = sanitize_open_world_director_output("导演自行续写了一整段剧情")
    assert clean.startswith("<plot_directive>")
    assert "不要无视玩家本回合输入" in clean


def test_director_output_accepts_markdown_fenced_directive_opening():
    raw = (
        "## 步骤一：事件状态声明\n\n"
        '`<event_trigger event_id="1"/>`\n\n'
        "## 步骤二：剧情指令\n\n"
        "```plot_directive\n"
        "- 本回合主推：缺页档案\n"
        "- 节奏：悬疑\n"
        "</plot_directive>\n"
        "```"
    )

    clean = sanitize_open_world_director_output(raw)

    assert '<event_trigger event_id="1"/>' in clean
    assert "<plot_directive>" in clean
    assert "本回合主推：缺页档案" in clean
    assert "## 步骤" not in clean
    assert "```" not in clean


def test_director_output_accepts_standard_markdown_fenced_directive():
    raw = (
        "## 步骤一：事件状态声明\n\n"
        '`<event_trigger event_id="1"/>`\n\n'
        "## 步骤二：剧情指令\n\n"
        "```plot_directive\n"
        "- 本回合主推：缺页档案\n"
        "- 节奏：揭露\n"
        "```"
    )

    clean = sanitize_open_world_director_output(raw)

    assert '<event_trigger event_id="1"/>' in clean
    assert "<plot_directive>" in clean
    assert "本回合主推：缺页档案" in clean
    assert "</plot_directive>" in clean
    assert "```" not in clean


def test_event_declarations_follow_current_lifecycle_state():
    text = (
        '<event_trigger event_id="缺页档案"/>\n'
        '<event_complete event_id="缺页档案"/>\n'
        '<event_complete event_id="封锁线后的铜票"/>\n'
        '<event_trigger event_id="未知事件"/>\n'
        '<plot_directive>继续调查</plot_directive>'
    )

    filtered = filter_event_declarations(text, [
        {"id": 1, "name": "缺页档案", "status": "triggered"},
        {"id": 2, "name": "封锁线后的铜票", "status": "pending"},
    ])

    assert '<event_complete event_id="缺页档案"/>' in filtered
    assert '<event_trigger event_id="缺页档案"/>' not in filtered
    assert "封锁线后的铜票" not in filtered
    assert "未知事件" not in filtered
    assert "<plot_directive>继续调查</plot_directive>" in filtered


def test_selected_event_fact_is_injected_for_scene_grounding():
    enriched = enrich_plot_directive(
        "<plot_directive>\n- 本回合主推：缺页档案\n</plot_directive>",
        [{
            "id": 1,
            "name": "缺页档案",
            "status": "triggered",
            "summary_md": "档案被人为撕去关键页，韩策知道最后接触者。",
            "completion_criteria_md": "取得最后接触者的可核验证词。",
        }],
    )

    assert "事件事实（唯一依据）" in enriched
    assert "韩策知道最后接触者" in enriched
    assert "事件状态：triggered" in enriched
    assert "完成判据：取得最后接触者的可核验证词" in enriched


def test_model_supplied_event_fact_cannot_override_framework_fact():
    enriched = enrich_plot_directive(
        "<plot_directive>\n"
        "- 本回合主推：缺页档案\n"
        "- 事件事实（唯一依据）：沈砚已经确认幕后人物。\n"
        "- 事件状态：completed\n"
        "</plot_directive>",
        [{
            "id": 1,
            "name": "缺页档案",
            "status": "triggered",
            "summary_md": "旧海关站的失踪档案被人为撕去关键页。",
            "completion_criteria_md": "取得可核验的档案编号。",
        }],
    )

    assert "沈砚已经确认幕后人物" not in enriched
    assert "事件状态：completed" not in enriched
    assert "旧海关站的失踪档案被人为撕去关键页" in enriched
    assert "事件状态：triggered" in enriched
    assert "完成判据：取得可核验的档案编号" in enriched
