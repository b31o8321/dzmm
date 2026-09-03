from dzmm_vnext.narrative import (
    advance_world_events,
    apply_gm_actions,
    extract_npc_dialogues,
    initial_state,
    schedule_npc_initiative,
    settle_pending_interactions,
    settle_world_events,
)
from dzmm_vnext.narrative_output import clean_narrative_output, extract_gm_actions
from dzmm_vnext.story_beats import _state_feedback, build_turn_story_beat


def _definition() -> dict:
    return {
        "name": "测试世界",
        "locations": [{"id": "harbor", "name": "港口"}],
        "npcs": [{"id": "lan", "name": "岚", "contact_cooldown_turns": 4}],
        "character_cards": [],
        "events": [],
        "story": {"chapters": [], "flags": [], "relationships": [], "relationship_events": [], "routes": [], "endings": []},
        "ruleset": {"id": "trpg", "enabled_capabilities": ["trpg"]},
    }


def test_state_feedback_uses_player_event_names_and_describes_new_threads() -> None:
    definition = _definition()
    definition["events"] = [{"id": "storm", "name": "风暴逼近"}]

    labels = _state_feedback(
        definition,
        [
            {"type": "world_event_activated", "event_id": "storm"},
            {
                "type": "plot_thread_introduced",
                "description": "失踪的航图指向北岸",
            },
        ],
    )

    assert labels == ["世界事件开始影响局势：风暴逼近", "新的剧情线：失踪的航图指向北岸"]
    assert "storm" not in " ".join(labels)


def test_npc_initiative_is_queued_once_and_respects_cooldown() -> None:
    definition = _definition()
    state = initial_state(definition, {"id": "hero", "name": "旅人", "profile": {}})
    state["revision"] = 1
    state["npc_state"]["lan"]["met"] = True

    scheduled = schedule_npc_initiative(state, definition, "run-a")
    assert scheduled and scheduled["npc_name"] == "岚"
    assert state["pending_interactions"][0]["kind"] == "npc_initiative"
    assert schedule_npc_initiative(state, definition, "run-a") is None

    outcomes: list[dict] = []
    settle_pending_interactions(state, outcomes)
    assert outcomes[0]["type"] == "npc_initiative_resolved"
    assert state["pending_interactions"] == []

    state["revision"] = 2
    assert schedule_npc_initiative(state, definition, "run-a") is None
    state["revision"] = 5
    assert schedule_npc_initiative(state, definition, "run-a") is not None


def test_npc_initiative_story_beat_explains_that_player_should_respond() -> None:
    definition = _definition()
    state = initial_state(definition, {"id": "hero", "name": "旅人", "profile": {}})
    state["pending_interactions"] = [
        {"kind": "npc_initiative", "npc_name": "岚", "status": "pending"}
    ]

    beat = build_turn_story_beat(definition, state, "岚在门口等你。", [])

    assert beat["objective"] == "岚 主动找到了你，正在等待回应。"
    assert "回应这次主动联系" in beat["guidance"]


def test_npc_dialogue_is_recorded_as_structured_memory() -> None:
    definition = _definition()
    dialogues = extract_npc_dialogues("雾里，岚：“别点灯，后面有人。”", definition)
    assert dialogues == [{"speaker": "岚", "text": "别点灯，后面有人。"}]


def test_authored_world_event_activates_once_at_its_turn_gate() -> None:
    definition = _definition()
    definition["events"] = [
        {
            "id": "storm",
            "name": "潮暴",
            "kind": "weather",
            "trigger_turn": 2,
            "importance": 3,
            "summary": "海面突然升起黑色风墙。",
        }
    ]
    state = initial_state(definition, {"id": "hero", "name": "旅人", "profile": {}})
    state["revision"] = 1
    assert advance_world_events(state, definition) == []
    state["revision"] = 2
    activated = advance_world_events(state, definition)
    assert activated == [{"type": "world_event_activated", "event_id": "storm"}]
    assert state["active_events"][0]["status"] == "active"
    assert advance_world_events(state, definition) == []


def test_gm_actions_are_private_allowlisted_and_deduplicated() -> None:
    state = initial_state(_definition(), {"id": "hero", "name": "旅人", "profile": {}})
    state["revision"] = 3
    visible, actions = extract_gm_actions(
        "潮声里传来一阵脚步。\n\n<!--DZMM_ACTIONS "
        '{"actions":[{"type":"introduce_plot_thread","id":"missing-lantern",'
        '"thread_type":"mystery","description":"有人在港口藏起了雾灯。",'
        '"importance":2},{"type":"set_flags","flag_id":"unsafe"}]}-->'
    )
    assert visible == "潮声里传来一阵脚步。"
    assert len(actions) == 2
    outcomes = apply_gm_actions(state, actions)
    assert outcomes == [
        {
            "type": "plot_thread_introduced",
            "thread_id": "missing-lantern",
            "thread_type": "mystery",
            "description": "有人在港口藏起了雾灯。",
        }
    ]
    assert state["plot_threads"][0]["introduced_turn"] == 3
    assert clean_narrative_output(
        "正文<!--DZMM_ACTIONS {\"actions\":[] }-->"
    ) == "正文"
    assert apply_gm_actions(state, actions) == []


def test_narrative_cleanup_removes_qwen_choice_meta_but_keeps_scene() -> None:
    raw = (
        "#### 灯塔顶端\n\n"
        "艾莉森推开暗门，潮声从石缝里涌上来。\n\n"
        "### 可能的选择与结果\n\n"
        "1. 仔细研究日记内容\n"
        "   - 找到潮门关闭的线索。\n\n"
        "#### 神秘女子现身\n\n"
        "她在雾里抬手，示意两人保持安静。\n\n"
        "#### 行动钩子\n\n"
        "- 回应神秘女子\n"
        "- 忽略她"
    )
    assert clean_narrative_output(raw) == (
        "灯塔顶端\n\n"
        "艾莉森推开暗门，潮声从石缝里涌上来。\n\n"
        "神秘女子现身\n\n"
        "她在雾里抬手，示意两人保持安静。"
    )


def test_narrative_cleanup_removes_inline_markdown_and_followup_meta() -> None:
    raw = (
        "### NPC 反应\n\n"
        "**神秘女子**：“潮门今晚会开启。”\n\n"
        "### 选择：\n"
        "1. 询问更多信息\n"
        "2. 立即离开\n\n"
        "### 后续行动\n"
        "- 前往月光港\n\n"
        "### 情节推进\n\n"
        "他们带着线索返回港口。"
    )
    assert clean_narrative_output(raw) == (
        "NPC 反应\n\n"
        "神秘女子：“潮门今晚会开启。”\n\n"
        "情节推进\n\n"
        "他们带着线索返回港口。"
    )


def test_narrative_cleanup_drops_model_self_analysis_and_latex() -> None:
    raw = (
        "艾尔文抬头看向碑石，指尖捕捉到一缕新出现的蓝光。\n\n"
        "根据故事发展的逻辑，接下来的情节将进入第七章（chapter_id: ch7）。\n\n"
        "- 选择向艾尔文询问进展（choice_id: ask-7）\n\n"
        "\\[\\boxed{失联的导航员}\\]"
    )
    assert clean_narrative_output(raw) == "艾尔文抬头看向碑石，指尖捕捉到一缕新出现的蓝光。"


def test_gm_actions_change_npc_reputation_with_hard_bounds() -> None:
    state = initial_state(_definition(), {"id": "hero", "name": "旅人", "profile": {}})
    state["revision"] = 4
    outcomes = apply_gm_actions(
        state,
        [
            {
                "type": "adjust_npc_reputation",
                "npc_id": "lan",
                "delta": 18,
                "reason_key": "kept_promise",
            },
            {
                "type": "adjust_npc_reputation",
                "npc_id": "lan",
                "delta": 99,
                "reason_key": "too_large",
            },
            {
                "type": "adjust_npc_reputation",
                "npc_id": "lan",
                "delta": 4,
                "reason_key": "duplicate_same_turn",
            },
        ],
    )

    assert state["npc_state"]["lan"]["reputation"] == 18
    assert outcomes == [
        {
            "type": "npc_reputation_changed",
            "npc_id": "lan",
            "npc_name": "岚",
            "previous": 0,
            "delta": 18,
            "reputation": 18,
            "reason_key": "kept_promise",
        }
    ]


def test_npc_reputation_predicate_can_gate_world_events() -> None:
    definition = _definition()
    definition["events"] = [
        {
            "id": "lan-trusts-hero",
            "name": "岚的信任",
            "summary": "岚决定把潮门的秘密交给你。",
            "trigger_conditions": {
                "type": "npc_reputation",
                "npc_id": "lan",
                "op": "gte",
                "value": 15,
            },
        }
    ]
    state = initial_state(definition, {"id": "hero", "name": "旅人", "profile": {}})
    state["revision"] = 1
    assert advance_world_events(state, definition) == []
    apply_gm_actions(
        state,
        [{"type": "adjust_npc_reputation", "npc_id": "lan", "delta": 15}],
    )

    assert advance_world_events(state, definition) == [
        {"type": "world_event_activated", "event_id": "lan-trusts-hero"}
    ]


def test_world_event_predicates_use_location_flags_and_faction_tension() -> None:
    definition = _definition()
    definition["factions"] = [
        {
            "id": "watchers",
            "name": "守望会",
            "initial_tension": 7,
            "tension_rules": {"passive_gain_per_turn": 3, "threshold_conflict": 10},
        }
    ]
    definition["events"] = [
        {
            "id": "harbor-alarm",
            "name": "港口警报",
            "summary": "守望会的钟声突然响起。",
            "trigger_conditions": {
                "type": "all",
                "children": [
                    {"type": "location_reached", "location_id": "harbor"},
                    {"type": "faction_tension", "faction_id": "watchers", "op": "gte", "value": 10},
                ],
            },
        }
    ]
    state = initial_state(definition, {"id": "hero", "name": "旅人", "profile": {}})
    state["revision"] = 1

    activated = advance_world_events(state, definition)

    assert activated == [{"type": "world_event_activated", "event_id": "harbor-alarm"}]
    assert state["faction_state"]["watchers"]["tension"] == 10
    assert state["faction_state"]["watchers"]["last_advanced_turn"] == 1
    assert advance_world_events(state, definition) == []
    assert state["faction_state"]["watchers"]["tension"] == 10


def test_completed_event_advances_campaign_phase_once() -> None:
    definition = _definition()
    definition["story"]["flags"] = [{"id": "gate-open", "default": False, "writers": []}]
    definition["story"]["campaign"] = {
        "id": "campaign-main",
        "name": "港口战役",
        "phases": [
            {
                "id": "phase-1",
                "name": "打开闸门",
                "description": "",
                "key_event_ids": ["gate-event"],
                "required_count": 1,
            },
            {
                "id": "phase-2",
                "name": "进入内港",
                "description": "",
                "key_event_ids": [],
                "required_count": 1,
            },
        ],
    }
    definition["events"] = [
        {
            "id": "gate-event",
            "name": "闸门开启",
            "trigger_turn": 1,
            "completion_conditions": {"type": "flag", "flag_id": "gate-open", "value": True},
            "campaign_phase_id": "phase-1",
        }
    ]
    state = initial_state(definition, {"id": "hero", "name": "旅人", "profile": {}})
    state["revision"] = 1
    assert state["campaign_state"]["current_phase_id"] == "phase-1"
    assert advance_world_events(state, definition) == [
        {"type": "world_event_activated", "event_id": "gate-event"}
    ]
    state["flags"]["gate-open"] = True
    outcomes: list[dict] = []
    settle_world_events(state, definition, outcomes)

    assert state["active_events"][0]["status"] == "resolved"
    assert state["campaign_state"]["completed_event_ids"] == ["gate-event"]
    assert state["campaign_state"]["completed_phase_ids"] == ["phase-1"]
    assert state["campaign_state"]["current_phase_id"] == "phase-2"
    assert [item["type"] for item in outcomes] == [
        "world_event_resolved",
        "campaign_phase_completed",
        "campaign_phase_advanced",
    ]
    settle_world_events(state, definition, outcomes)
    assert state["campaign_state"]["completed_event_ids"] == ["gate-event"]
