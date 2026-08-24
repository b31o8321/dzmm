from __future__ import annotations

import re
from typing import Any

_DIALOGUE_PATTERN = re.compile(
    r"(?P<speaker>[A-Za-z0-9_\u4e00-\u9fff·]{1,20})[：:]\s*[“\"](?P<text>[^”\"]+)[”\"]"
)


def build_deterministic_narrative(
    definition: dict[str, Any], state: dict[str, Any], player_input: str
) -> str:
    """Fallback prose for Runs without a configured model."""
    hero_name = str(state["hero"]["name"])
    location = next(
        (
            item
            for item in definition.get("locations") or []
            if isinstance(item, dict) and item.get("id") == state.get("location_id")
        ),
        None,
    )
    location_name = str((location or {}).get("name") or definition.get("name") or "眼前的场景")
    if state.get("ending"):
        return (
            f"{hero_name}在{location_name}作出了「{player_input}」的决定。一路留下的选择在此汇成答案；"
            "这段旅程已经抵达属于它的结局。"
        )
    character = next(iter(definition.get("character_cards") or []), None)
    narrative = (
        f"{hero_name}在{location_name}选择了「{player_input}」。这个决定已经改变了眼前的局势，"
        "新的线索正在当前场景中浮现。"
    )
    if not character:
        return narrative
    speaker = str(character.get("name") or "同行者")
    return f"{narrative}\n\n{speaker}：“我看见你的选择了。接下来，别忽略眼前的变化。”"


def build_opening_story_beat(definition: dict[str, Any], hero: dict[str, Any]) -> dict[str, Any]:
    """Build the persisted, player-visible opening shared by every local host."""
    story = definition.get("story") or {}
    chapters = story.get("chapters") or []
    chapter = chapters[0] if chapters else {}
    locations = definition.get("locations") or []
    location = locations[0] if locations else {}
    cards = definition.get("character_cards") or []
    lore_entries = (definition.get("lorebook") or {}).get("entries") or []

    world_name = str(definition.get("name") or "未命名世界")
    hero_name = str(hero.get("name") or "旅行者")
    cast = list(definition.get("npcs") or []) + list(cards)
    character = next(
        (
            item
            for item in cast
            if isinstance(item, dict) and str(item.get("name") or "").strip() not in {"", hero_name}
        ),
        cast[0] if cast and isinstance(cast[0], dict) else None,
    )
    chapter_title = str(chapter.get("title") or "序章")
    location_name = str(location.get("name") or world_name)
    lore = str((lore_entries[0] if lore_entries else {}).get("body") or "").strip()
    choices = [
        str(choice.get("label"))
        for choice in chapter.get("choices") or []
        if str(choice.get("label") or "").strip()
    ]

    narrative_parts = [
        f"{chapter_title}。{hero_name}抵达{location_name}，{world_name}的故事从此刻开始。"
    ]
    if lore:
        narrative_parts.append(lore)

    dialogue = None
    if character:
        speaker = str(character.get("name") or "陌生人")
        dialogue = {
            "speaker": speaker,
            "text": f"“{hero_name}，别让这里替你作出第一个决定。”",
        }

    objective = f"确认眼前的局势，决定如何进入「{chapter_title}」。"
    guidance = (
        f"以下选项只是建议：{'、'.join(choices)}；你也可以直接描述任何行动。"
        if choices
        else "描述你准备采取的任何行动，世界会根据行动继续推演。"
    )
    return {
        "kind": "opening",
        "title": chapter_title,
        "location": location_name,
        "narrative": "\n\n".join(narrative_parts),
        "dialogue": dialogue,
        "objective": objective,
        "guidance": guidance,
    }


def build_turn_story_beat(
    definition: dict[str, Any],
    state: dict[str, Any],
    narrative: str,
    outcomes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project a completed, Python-approved turn into player-facing story UI."""
    locations = {item["id"]: item["name"] for item in definition.get("locations") or []}
    chapters = {item["id"]: item for item in (definition.get("story") or {}).get("chapters") or []}
    chapter_state = state.get("chapter") or {}
    chapter = chapters.get(chapter_state.get("id"), {})
    ending = state.get("ending")
    pending = state.get("pending_interactions") or []
    choices = [
        str(choice.get("label"))
        for choice in chapter.get("choices") or []
        if choice.get("id") not in set(chapter_state.get("resolved_choice_ids") or [])
    ]
    if ending:
        objective = "这段旅程已经抵达正式结局。"
        guidance = "你可以回看旅程，或从同一个世界开始新的 Run。"
        ending_label = {
            "good": "好结局",
            "normal": "普通结局",
            "bad": "坏结局",
            "hidden": "隐藏结局",
        }.get(str(ending.get("kind") or ""), "旅程结局")
        title = f"结局 · {ending_label}"
    else:
        title = str(chapter.get("title") or "故事继续")
        if pending:
            npc_name = str(pending[0].get("npc_name") or "某位角色")
            objective = f"{npc_name} 主动找到了你，正在等待回应。"
            guidance = "先回应这次主动联系，也可以直接描述你准备采取的行动。"
        else:
            objective = f"继续推进「{title}」。"
            guidance = (
                f"接下来可以选择：{'、'.join(choices)}；也可以直接描述任何行动。"
                if choices
                else "描述你接下来要做的任何行动。"
            )
    visible_narrative, dialogue = _split_dialogue(narrative, definition)
    dialogues = _extract_dialogues(narrative, definition)
    return {
        "kind": "ending" if ending else "narrative",
        "title": title,
        "location": locations.get(state.get("location_id"), str(state.get("location_id") or "")),
        "narrative": visible_narrative,
        "dialogue": dialogue,
        "dialogues": dialogues,
        "objective": objective,
        "guidance": guidance,
        "state_feedback": _state_feedback(definition, outcomes or []),
    }


def _split_dialogue(
    narrative: str, definition: dict[str, Any]
) -> tuple[str, dict[str, str] | None]:
    matched = _DIALOGUE_PATTERN.search(narrative)
    if matched:
        prose = (narrative[: matched.start()] + narrative[matched.end() :]).strip()
        return prose or narrative, {
            "speaker": matched.group("speaker"),
            "text": f"“{matched.group('text').strip()}”",
        }
    quoted = re.search(r"[“\"](?P<text>[^”\"]+)[”\"]", narrative)
    character = next(iter(definition.get("character_cards") or []), None)
    if not quoted or not character:
        return narrative, None
    prose = (narrative[: quoted.start()] + narrative[quoted.end() :]).strip()
    return prose or narrative, {
        "speaker": str(character.get("name") or "同行者"),
        "text": f"“{quoted.group('text').strip()}”",
    }


def _extract_dialogues(narrative: str, definition: dict[str, Any]) -> list[dict[str, str]]:
    """Return all recognizable NPC dialogue while keeping legacy `dialogue`."""

    names = [
        str(item.get("name") or "")
        for item in (definition.get("npcs") or []) + (definition.get("character_cards") or [])
    ]
    dialogues: list[dict[str, str]] = []
    for name in dict.fromkeys(name for name in names if name):
        pattern = re.compile(
            rf"{re.escape(name)}\s*[：:]\s*[“「\"](?P<text>[^”」\"]+)[”」\"]"
        )
        dialogues.extend(
            {"speaker": name, "text": match.group("text").strip()}
            for match in pattern.finditer(narrative)
        )
    return dialogues[:6]


def _state_feedback(definition: dict[str, Any], outcomes: list[dict[str, Any]]) -> list[str]:
    resources = {
        item["id"]: item.get("name", item["id"]) for item in definition.get("resources") or []
    }
    characters = {
        item["id"]: item.get("name", item["id"]) for item in definition.get("character_cards") or []
    }
    chapters = {
        item["id"]: item.get("title", item["id"])
        for item in (definition.get("story") or {}).get("chapters") or []
    }
    routes = {
        item["id"]: item.get("name", item["id"])
        for item in (definition.get("story") or {}).get("routes") or []
    }
    events = {
        item["id"]: item.get("name") or item.get("title") or item["id"]
        for item in definition.get("events") or []
        if item.get("id")
    }
    labels: list[str] = []
    for outcome in outcomes:
        kind = outcome.get("type")
        if kind == "grant_resource":
            labels.append(
                f"获得 {resources.get(outcome.get('resource_id'), outcome.get('resource_id'))} "
                f"×{outcome.get('quantity')}"
            )
        elif kind == "apply_relationship_event":
            name = characters.get(outcome.get("character_card_id"), outcome.get("relationship_id"))
            dimension_names = {"affection": "好感", "trust": "信任"}
            deltas = " / ".join(
                f"{dimension_names.get(key, key)} {value:+d}"
                for key, value in (outcome.get("deltas") or {}).items()
            )
            labels.append(f"与 {name}：{deltas}" if deltas else f"与 {name} 的关系发生变化")
        elif kind == "advance_chapter" and outcome.get("next_chapter_id"):
            labels.append(
                f"进入 {chapters.get(outcome['next_chapter_id'], outcome['next_chapter_id'])}"
            )
        elif kind == "lock_route":
            labels.append(
                f"路线锁定：{routes.get(outcome.get('route_id'), outcome.get('route_id'))}"
            )
        elif kind == "npc_initiative_scheduled":
            labels.append(f"{outcome.get('npc_name', 'NPC')} 将主动联系你")
        elif kind == "npc_initiative_resolved":
            labels.append(f"已回应 {outcome.get('npc_name', 'NPC')} 的主动联系")
        elif kind == "npc_reputation_changed":
            labels.append(
                f"{outcome.get('npc_name', 'NPC')} 对你的态度变化：声誉 {outcome.get('delta', 0):+d}"
            )
        elif kind == "world_event_activated":
            event_id = outcome.get("event_id")
            labels.append(f"世界事件开始影响局势：{events.get(event_id, '新的事件')}")
        elif kind == "plot_thread_introduced":
            description = str(outcome.get("description") or "新的线索正在展开")
            labels.append(f"新的剧情线：{description}")
        elif kind == "plot_thread_resolved":
            labels.append("一条剧情线已经得到回应")
        elif kind == "hidden_event_created":
            description = str(outcome.get("description") or "新的暗线正在酝酿")
            labels.append(f"新的暗线：{description}")
        elif kind == "hidden_event_resolved":
            labels.append("一条隐藏事件已经解决")
        elif kind == "move":
            locations = {
                item["id"]: item.get("name", item["id"])
                for item in definition.get("locations") or []
            }
            labels.append(
                f"抵达 {locations.get(outcome.get('location_id'), outcome.get('location_id'))}"
            )
        elif kind == "lock_ending":
            labels.append("结局已锁定")
    return labels
