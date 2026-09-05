from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any


class NarrativeRuleError(ValueError):
    pass


_CAPABILITIES_BY_RULESET = {
    "trpg": {"trpg", "resources", "combat"},
    "story_adventure": {"chapters", "choices", "relationships", "routes", "endings", "resources"},
    "relationship_drama": {"chapters", "choices", "relationships", "routes", "endings", "resources"},
    "hybrid": {"trpg", "combat", "chapters", "choices", "relationships", "routes", "endings", "resources"},
}


def validate_definition(definition: dict[str, Any]) -> None:
    ruleset = definition["ruleset"]
    ruleset_id = ruleset["id"]
    capabilities = set(ruleset["enabled_capabilities"])
    if not capabilities <= _CAPABILITIES_BY_RULESET[ruleset_id]:
        raise NarrativeRuleError(f"ruleset {ruleset_id} contains unsupported capability")
    if ruleset_id == "trpg" and "trpg" not in capabilities:
        raise NarrativeRuleError("trpg ruleset requires trpg capability")
    if ruleset_id != "trpg" and not {"chapters", "choices", "endings"} <= capabilities:
        raise NarrativeRuleError(f"ruleset {ruleset_id} requires chapters, choices and endings")

    story = definition["story"]
    _require_unique(story["chapters"], "chapter")
    _require_unique(story["flags"], "story flag")
    _require_unique(story["relationships"], "relationship")
    _require_unique(story["relationship_events"], "relationship event")
    _require_unique(story["routes"], "route")
    _require_unique(story["endings"], "ending")
    _require_unique(definition["character_cards"], "character card")
    _require_unique(definition["resources"], "resource")

    chapter_ids = {item["id"] for item in story["chapters"]}
    if bool(story["chapters"]) != ("chapters" in capabilities):
        raise NarrativeRuleError("chapters must exist exactly when chapters capability is enabled")
    if story["chapters"]:
        orders = [chapter["order"] for chapter in story["chapters"]]
        if sorted(orders) != list(range(1, len(orders) + 1)):
            raise NarrativeRuleError("chapter order must be contiguous from 1")
        for chapter in story["chapters"]:
            if chapter["next_chapter_id"] is not None and chapter["next_chapter_id"] not in chapter_ids:
                raise NarrativeRuleError("chapter references an unknown next chapter")
        if sum(chapter["next_chapter_id"] is None for chapter in story["chapters"]) != 1:
            raise NarrativeRuleError("story needs exactly one terminal chapter")

    card_ids = {item["id"] for item in definition["character_cards"]}
    relationships = {item["id"]: item for item in story["relationships"]}
    for relationship in relationships.values():
        if relationship["character_card_id"] not in card_ids:
            raise NarrativeRuleError("relationship references an unknown character card")
        for dimension in relationship["dimensions"].values():
            if not dimension["min"] <= dimension["initial"] <= dimension["max"]:
                raise NarrativeRuleError("relationship dimension initial value is outside its bounds")
    for event in story["relationship_events"]:
        relationship = relationships.get(event["relationship_id"])
        if relationship is None:
            raise NarrativeRuleError("relationship event references an unknown relationship")
        dimensions = relationship["dimensions"]
        if not set(event["deltas"]) <= set(dimensions):
            raise NarrativeRuleError("relationship event changes an undefined dimension")
    if (story["relationships"] or story["relationship_events"]) and "relationships" not in capabilities:
        raise NarrativeRuleError("relationships require relationships capability")
    if story["routes"] and "routes" not in capabilities:
        raise NarrativeRuleError("routes require routes capability")
    if story["endings"] and "endings" not in capabilities:
        raise NarrativeRuleError("endings require endings capability")

    flag_ids = {item["id"] for item in story["flags"]}
    relationship_event_ids = {item["id"] for item in story["relationship_events"]}
    route_ids = {item["id"] for item in story["routes"]}
    resource_ids = {item["id"] for item in definition["resources"]}
    seen_choices: set[str] = set()
    for chapter in story["chapters"]:
        for choice in chapter["choices"]:
            if choice["id"] in seen_choices:
                raise NarrativeRuleError("choice ids must be globally unique")
            seen_choices.add(choice["id"])
            for effect in choice["effects"]:
                _validate_effect(effect, choice["id"], flag_ids, relationship_event_ids, route_ids, resource_ids)
    for flag in story["flags"]:
        if not set(flag["writers"]) <= {f"choice:{choice_id}" for choice_id in seen_choices}:
            raise NarrativeRuleError("story flag declares an unknown writer")


def initial_state(definition: dict[str, Any], hero: dict[str, Any]) -> dict[str, Any]:
    story = definition["story"]
    chapters = sorted(story["chapters"], key=lambda chapter: chapter["order"])
    locations = definition.get("locations") or []
    npc_definitions: list[dict[str, Any]] = []
    seen_npc_ids: set[str] = set()
    for npc in [*(definition.get("npcs") or []), *(definition.get("character_cards") or [])]:
        if npc.get("id") and npc["id"] not in seen_npc_ids:
            seen_npc_ids.add(npc["id"])
            npc_definitions.append(npc)
    npc_state = {
        npc["id"]: {
            "id": npc["id"],
            "name": npc["name"],
            "met": False,
            "location_id": npc.get("location_id"),
            "state": "unknown",
            "favor": int(npc.get("favor", 0) or 0),
            "faction_id": npc.get("faction_id"),
            "reputation": max(-100, min(100, _safe_int(npc.get("reputation", 0), 0))),
            "emotion": {},
            "last_seen_turn": 0,
            "last_spoke_turn": 0,
            "last_initiative_turn": 0,
            "cooldown_turns": max(1, int(npc.get("contact_cooldown_turns", 4) or 4)),
        }
        for npc in npc_definitions
    }
    faction_state = {
        faction["id"]: {
            "id": faction["id"],
            "name": faction["name"],
            "tension": max(0, min(100, _safe_int(faction.get("initial_tension", 0), 0))),
            "passive_gain_per_turn": max(
                0,
                min(
                    10,
                    _safe_int(
                        (
                            faction.get("tension_rules")
                            if isinstance(faction.get("tension_rules"), dict)
                            else {}
                        ).get("passive_gain_per_turn", 0),
                        0,
                    ),
                ),
            ),
            "threshold_conflict": max(
                1,
                min(
                    100,
                    _safe_int(
                        (
                            faction.get("tension_rules")
                            if isinstance(faction.get("tension_rules"), dict)
                            else {}
                        ).get("threshold_conflict", 80),
                        80,
                    ),
                ),
            ),
            "last_advanced_turn": 0,
        }
        for faction in definition.get("factions") or []
        if faction.get("id") and faction.get("name")
    }
    campaign = story.get("campaign") if isinstance(story.get("campaign"), dict) else None
    campaign_phases = campaign.get("phases") if campaign else []
    campaign_state = (
        {
            "id": campaign["id"],
            "name": campaign["name"],
            "current_phase_id": campaign_phases[0]["id"] if campaign_phases else None,
            "completed_phase_ids": [],
            "completed_event_ids": [],
        }
        if campaign and campaign.get("id") and campaign.get("name")
        else None
    )
    return {
        "schema_version": 3,
        "revision": 0,
        "hero": hero,
        "ruleset": deepcopy(definition["ruleset"]),
        "location_id": definition["locations"][0]["id"],
        "inventory": [],
        "entities": {},
        "events": {},
        "combat": {"participants": {}},
        "location_state": {
            location["id"]: {
                "known": index == 0,
                "visited_turns": [0] if index == 0 else [],
                "last_visited_turn": 0 if index == 0 else None,
                "scene_state": {},
            }
            for index, location in enumerate(locations)
        },
        "npc_state": npc_state,
        "faction_state": faction_state,
        "campaign_state": campaign_state,
        "active_events": [],
        "plot_threads": [],
        "pending_interactions": [],
        "chapter": (
            {"id": chapters[0]["id"], "status": "active", "resolved_choice_ids": []}
            if chapters
            else None
        ),
        "route": None,
        "flags": {flag["id"]: flag["default"] for flag in story["flags"]},
        "relationships": {
            relationship["id"]: {
                "dimensions": {
                    name: dimension["initial"]
                    for name, dimension in relationship["dimensions"].items()
                },
                "applied_events": {},
            }
            for relationship in story["relationships"]
        },
        "ending": None,
    }


def narrative_variation(
    definition: dict[str, Any], state: dict[str, Any], variation_seed: str
) -> dict[str, str]:
    """Return a bounded creative prompt for this Run/turn.

    The authored graph remains the source of truth for hard state transitions, but
    the GM needs a fresh pressure point on every turn.  Deriving it from the Run id
    (rather than the world definition) means replaying the same world does not
    replay the same scene prompt.
    """

    revision = int(state.get("revision") or 0)
    digest = hashlib.sha256(f"{variation_seed}:{revision}".encode()).hexdigest()
    candidates: list[str] = []
    for event in definition.get("events") or []:
        label = str(event.get("name") or event.get("title") or event.get("id") or "")
        if label:
            candidates.append(f"世界事件「{label}」出现新的迹象")
    for npc in definition.get("npcs") or []:
        label = str(npc.get("name") or npc.get("id") or "")
        if label:
            candidates.append(f"NPC「{label}」做出一个不完全符合预期的反应")
    for location in definition.get("locations") or []:
        label = str(location.get("name") or location.get("id") or "")
        if label:
            candidates.append(f"在「{label}」发现此前没有注意到的细节")
    for entry in (definition.get("lorebook") or {}).get("entries") or []:
        label = str(entry.get("title") or entry.get("id") or "")
        if label:
            candidates.append(f"让世界设定「{label}」以意外方式影响眼前局势")
    if not candidates:
        candidates = [
            "引入一个此前未见的环境变化或旁观者",
            "让一个 NPC 暴露与当前目标相冲突的动机",
            "埋下一个短期可追查、但不立即解释的线索",
            "让玩家的行动产生一个非预期但合理的代价或机会",
        ]
    index = int(digest[:8], 16) % len(candidates)
    return {
        "key": digest[:12],
        "directive": candidates[index],
        "turn": str(revision),
    }


def record_narrative_context(
    state: dict[str, Any],
    definition: dict[str, Any],
    variation_seed: str,
    player_input: str,
    narrative: str,
    outcomes: list[dict[str, Any]],
) -> None:
    """Persist a small GM memory without granting the model state-write authority."""

    _record_location_visit(state)
    dialogues = extract_npc_dialogues(narrative, definition)
    _record_npc_presence(state, definition, narrative, dialogues)
    context = state.setdefault("narrative_context", {})
    context["run_seed"] = variation_seed
    context["turn_index"] = int(state.get("revision") or 0)
    context["current_hook"] = narrative_variation(definition, state, variation_seed)
    recent = context.setdefault("recent_turns", [])
    recent.append(
        {
            "turn": int(state.get("revision") or 0),
            "player_input": player_input[:400],
            "narrative": narrative[:1200],
            "outcomes": deepcopy(outcomes[-8:]),
            "dialogues": dialogues[:6],
        }
    )
    del recent[:-6]


def extract_npc_dialogues(
    narrative: str, definition: dict[str, Any]
) -> list[dict[str, str]]:
    """Extract visible NPC dialogue into a stable, player-safe event shape."""

    dialogues: list[dict[str, str]] = []
    names = [str(npc.get("name") or "") for npc in definition.get("npcs") or []]
    names.extend(str(card.get("name") or "") for card in definition.get("character_cards") or [])
    for name in dict.fromkeys(name for name in names if name):
        pattern = re.compile(
            rf"{re.escape(name)}\s*[：:]\s*[“「\"](?P<text>[^”」\"]+)[”」\"]"
        )
        for match in pattern.finditer(narrative):
            dialogues.append({"speaker": name, "text": match.group("text").strip()})
    return dialogues[:6]


def schedule_npc_initiative(
    state: dict[str, Any], definition: dict[str, Any], variation_seed: str
) -> dict[str, Any] | None:
    """Queue one eligible NPC interaction for the next player-visible turn."""

    if state.get("ending") or state.get("pending_interactions"):
        return None
    current_location = state.get("location_id")
    revision = int(state.get("revision") or 0)
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for npc_id, npc in (state.get("npc_state") or {}).items():
        if not npc.get("met"):
            continue
        last = int(npc.get("last_initiative_turn") or 0)
        cooldown = max(1, int(npc.get("cooldown_turns", 4) or 4))
        if last and revision - last < cooldown:
            continue
        npc_location = npc.get("location_id")
        if npc_location not in (None, current_location):
            continue
        emotion = npc.get("emotion") or {}
        emotion_score = max((int(value) for value in emotion.values()), default=0)
        reputation = int(npc.get("reputation", 0) or 0)
        score = (
            10
            + max(0, int(npc.get("favor", 0) or 0)) // 5
            + max(0, reputation) // 10
            + max(0, emotion_score) // 10
        )
        tie_breaker = hashlib.sha256(f"{variation_seed}:{revision}:{npc_id}".encode()).hexdigest()
        candidates.append((score, tie_breaker, npc))
    if not candidates:
        return None
    _score, _tie_breaker, selected = max(candidates, key=lambda item: (item[0], item[1]))
    selected["last_initiative_turn"] = revision
    interaction = {
        "id": f"npc-initiative-{revision}-{selected['id']}",
        "kind": "npc_initiative",
        "npc_id": selected["id"],
        "npc_name": selected["name"],
        "location_id": current_location,
        "created_turn": revision,
        "status": "pending",
        "instruction": f"让 {selected['name']} 主动联系玩家，带来一个具体消息、请求或意外。",
    }
    state.setdefault("pending_interactions", []).append(interaction)
    return {"type": "npc_initiative_scheduled", **interaction}


def advance_world_events(
    state: dict[str, Any], definition: dict[str, Any]
) -> list[dict[str, Any]]:
    """Activate authored world events when their turn gate is reached."""

    revision = int(state.get("revision") or 0)
    _advance_faction_tensions(state)
    active_events = state.setdefault("active_events", [])
    known = {str(event.get("id")): event for event in active_events}
    outcomes: list[dict[str, Any]] = []
    for event in definition.get("events") or []:
        event_id = str(event.get("id") or "")
        if not event_id or event_id in known:
            continue
        campaign_phase_id = event.get("campaign_phase_id")
        campaign_state = state.get("campaign_state")
        if campaign_phase_id and (
            not isinstance(campaign_state, dict)
            or campaign_state.get("current_phase_id") != campaign_phase_id
        ):
            continue
        trigger_turn = event.get("trigger_turn")
        initial_active = bool(event.get("initial_active"))
        try:
            due = trigger_turn is not None and revision >= int(trigger_turn)
        except (TypeError, ValueError):
            due = False
        trigger_conditions = event.get("trigger_conditions") or event.get("trigger")
        if trigger_conditions:
            if not _evaluate_event_predicate(trigger_conditions, state):
                continue
            due = True
        if not initial_active and not due:
            continue
        try:
            severity = max(1, min(5, int(event.get("importance", 2) or 2)))
        except (TypeError, ValueError):
            severity = 2
        active_events.append(
            {
                "id": event_id,
                "kind": str(event.get("kind") or "world_event"),
                "status": "active",
                "subject": str(event.get("scope_ref") or ""),
                "severity": severity,
                "description": str(event.get("summary") or event.get("description") or event.get("name") or ""),
                "consequence": str(event.get("consequence") or ""),
                "introduced_turn": revision,
                "trigger_turn": int(trigger_turn) if trigger_turn is not None else None,
                "resolved_turn": None,
                "resolution": "",
                "completion_conditions": dict(
                    event.get("completion_conditions") or event.get("completion") or {}
                ),
                "campaign_phase_id": campaign_phase_id,
            }
        )
        outcomes.append({"type": "world_event_activated", "event_id": event_id})
    return outcomes


def settle_world_events(
    state: dict[str, Any], definition: dict[str, Any], outcomes: list[dict[str, Any]]
) -> None:
    """Resolve authored events whose Python-verifiable completion conditions pass."""

    revision = int(state.get("revision") or 0)
    for event in state.get("active_events") or []:
        if (
            event.get("status") == "active"
            and event.get("completion_conditions")
            and _evaluate_event_predicate(event["completion_conditions"], state)
        ):
            event["status"] = "resolved"
            event["resolved_turn"] = revision
            event["resolution"] = "完成条件已满足"
            outcomes.append({"type": "world_event_resolved", "event_id": event.get("id")})
        if event.get("status") == "resolved":
            _record_campaign_event(state, definition, str(event.get("id") or ""), outcomes)


def _record_campaign_event(
    state: dict[str, Any], definition: dict[str, Any], event_id: str, outcomes: list[dict[str, Any]]
) -> None:
    campaign_state = state.get("campaign_state")
    campaign = (definition.get("story") or {}).get("campaign")
    if not isinstance(campaign_state, dict) or not isinstance(campaign, dict) or not event_id:
        return
    completed_events = campaign_state.setdefault("completed_event_ids", [])
    if event_id in completed_events:
        return
    completed_events.append(event_id)
    phases = campaign.get("phases") or []
    current_id = campaign_state.get("current_phase_id")
    current = next((phase for phase in phases if phase.get("id") == current_id), None)
    if not current:
        return
    required_events = set(current.get("key_event_ids") or [])
    required_count = max(1, _safe_int(current.get("required_count"), 1))
    completed_count = len(required_events & set(completed_events))
    if completed_count < required_count:
        return
    if current_id not in campaign_state.setdefault("completed_phase_ids", []):
        campaign_state["completed_phase_ids"].append(current_id)
        outcomes.append({"type": "campaign_phase_completed", "phase_id": current_id})
    index = next((index for index, phase in enumerate(phases) if phase.get("id") == current_id), -1)
    next_phase = phases[index + 1] if index >= 0 and index + 1 < len(phases) else None
    campaign_state["current_phase_id"] = next_phase.get("id") if next_phase else None
    if next_phase:
        outcomes.append({"type": "campaign_phase_advanced", "phase_id": next_phase.get("id")})


def _advance_faction_tensions(state: dict[str, Any]) -> None:
    revision = int(state.get("revision") or 0)
    for faction in (state.get("faction_state") or {}).values():
        if int(faction.get("last_advanced_turn") or 0) >= revision:
            continue
        gain = max(0, min(10, int(faction.get("passive_gain_per_turn", 0) or 0)))
        faction["tension"] = max(0, min(100, int(faction.get("tension", 0) or 0) + gain))
        faction["last_advanced_turn"] = revision


def _evaluate_event_predicate(predicate: Any, state: dict[str, Any]) -> bool:
    """Evaluate the old DZMM predicate vocabulary against the pure RunState."""

    if not isinstance(predicate, dict):
        return False
    kind = predicate.get("type")
    if kind in {"all", "any"}:
        children = predicate.get("children")
        if not isinstance(children, list):
            return False
        values = [_evaluate_event_predicate(child, state) for child in children]
        return all(values) if kind == "all" else any(values)
    if kind == "location_reached":
        return state.get("location_id") == predicate.get("location_id")
    if kind == "npc_state":
        npc_id = str(predicate.get("npc_id") or predicate.get("npc_template_id") or "")
        npc = (state.get("npc_state") or {}).get(npc_id)
        return bool(npc) and npc.get("state") == predicate.get("state")
    if kind == "npc_reputation":
        npc_id = str(predicate.get("npc_id") or "")
        npc = (state.get("npc_state") or {}).get(npc_id)
        if not npc:
            return False
        actual = _safe_int(npc.get("reputation", 0), 0)
        expected = _safe_int(predicate.get("value", 0), 0)
        op = predicate.get("op")
        return {
            "lte": actual <= expected,
            "lt": actual < expected,
            "gte": actual >= expected,
            "gt": actual > expected,
            "eq": actual == expected,
        }.get(op, False)
    if kind == "item_owned":
        item_name = predicate.get("item_name") or predicate.get("item_id")
        minimum = max(1, _safe_int(predicate.get("min_qty", 1), 1))
        return any(
            item.get("id") == item_name or item.get("name") == item_name
            for item in (state.get("inventory") or [])
            if isinstance(item, dict)
            and _safe_int(item.get("quantity", item.get("qty", 1)), 0) >= minimum
        )
    if kind == "faction_tension":
        faction_id = str(predicate.get("faction_id") or "")
        faction = (state.get("faction_state") or {}).get(faction_id)
        if not faction:
            return False
        actual = _safe_int(faction.get("tension", 0), 0)
        expected = _safe_int(predicate.get("value", 0), 0)
        op = predicate.get("op")
        return {
            "lte": actual <= expected,
            "lt": actual < expected,
            "gte": actual >= expected,
            "gt": actual > expected,
            "eq": actual == expected,
        }.get(op, False)
    if kind == "flag":
        return state.get("flags", {}).get(predicate.get("flag_id")) == predicate.get("value", True)
    return False


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_GM_ACTION_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_GM_THREAD_TYPES = {"quest", "hook", "mystery", "major_event"}
_GM_REPUTATION_REASON = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


def apply_gm_actions(state: dict[str, Any], actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the small, reversible portion of model-authored world evolution.

    Models may introduce or resolve narrative threads and hidden events.  They
    cannot write arbitrary state: IDs, lengths, enums, deduplication and
    resolution targets are all checked here, and invalid actions are ignored
    with an audit outcome rather than partially mutating the Run.
    """

    if not isinstance(actions, list):
        return []
    revision = int(state.get("revision") or 0)
    threads = state.setdefault("plot_threads", [])
    events = state.setdefault("active_events", [])
    outcomes: list[dict[str, Any]] = []
    changed_reputations: set[str] = set()
    for action in actions[:8]:
        if not isinstance(action, dict):
            continue
        action_type = str(action.get("type") or "").strip()
        if action_type == "introduce_plot_thread":
            thread_id = str(action.get("id") or "").strip()
            thread_kind = str(action.get("thread_type") or action.get("kind") or "hook").strip()
            description = str(action.get("description") or "").strip()
            if (
                not _GM_ACTION_ID.fullmatch(thread_id)
                or thread_kind not in _GM_THREAD_TYPES
                or not description
                or len(description) > 240
                or any(item.get("id") == thread_id for item in threads)
            ):
                continue
            try:
                importance = max(1, min(3, int(action.get("importance", 1) or 1)))
            except (TypeError, ValueError):
                importance = 1
            threads.append(
                {
                    "id": thread_id,
                    "type": thread_kind,
                    "description": description,
                    "introduced_turn": revision,
                    "importance": importance,
                    "status": "active",
                    "resolution": "",
                }
            )
            outcomes.append(
                {
                    "type": "plot_thread_introduced",
                    "thread_id": thread_id,
                    "thread_type": thread_kind,
                    "description": description,
                }
            )
        elif action_type == "resolve_plot_thread":
            thread_id = str(action.get("thread_id") or action.get("id") or "").strip()
            resolution = str(action.get("resolution") or "").strip()
            if not thread_id or not resolution or len(resolution) > 240:
                continue
            thread = next(
                (item for item in threads if item.get("id") == thread_id and item.get("status") == "active"),
                None,
            )
            if thread is None:
                continue
            thread["status"] = "resolved"
            thread["resolution"] = resolution
            outcomes.append({"type": "plot_thread_resolved", "thread_id": thread_id})
        elif action_type == "create_hidden_event":
            event_id = str(action.get("id") or "").strip()
            description = str(action.get("description") or action.get("summary") or "").strip()
            if (
                not _GM_ACTION_ID.fullmatch(event_id)
                or not description
                or len(description) > 240
                or any(item.get("id") == event_id for item in events)
            ):
                continue
            try:
                severity = max(1, min(5, int(action.get("severity", 2) or 2)))
            except (TypeError, ValueError):
                severity = 2
            events.append(
                {
                    "id": event_id,
                    "kind": "hidden_event",
                    "status": "active",
                    "subject": str(action.get("subject") or "")[:120],
                    "severity": severity,
                    "description": description,
                    "consequence": str(action.get("consequence") or "")[:240],
                    "introduced_turn": revision,
                    "trigger_turn": None,
                    "resolved_turn": None,
                    "resolution": "",
                }
            )
            outcomes.append(
                {"type": "hidden_event_created", "event_id": event_id, "description": description}
            )
        elif action_type == "resolve_hidden_event":
            event_id = str(action.get("event_id") or action.get("id") or "").strip()
            resolution = str(action.get("resolution") or "").strip()
            if not event_id or not resolution or len(resolution) > 240:
                continue
            event = next(
                (item for item in events if item.get("id") == event_id and item.get("status") == "active"),
                None,
            )
            if event is None:
                continue
            event["status"] = "resolved"
            event["resolved_turn"] = revision
            event["resolution"] = resolution
            outcomes.append({"type": "hidden_event_resolved", "event_id": event_id})
        elif action_type == "adjust_npc_reputation":
            npc_id = str(action.get("npc_id") or "").strip()
            reason = str(action.get("reason_key") or action.get("reason") or "narrative").strip()
            npc = (state.get("npc_state") or {}).get(npc_id)
            if not _GM_ACTION_ID.fullmatch(npc_id) or npc is None or npc_id in changed_reputations:
                continue
            if not _GM_REPUTATION_REASON.fullmatch(reason):
                continue
            try:
                delta = int(action.get("delta"))
            except (TypeError, ValueError):
                continue
            if delta == 0 or abs(delta) > 25:
                continue
            previous = max(-100, min(100, _safe_int(npc.get("reputation", 0), 0)))
            current = max(-100, min(100, previous + delta))
            npc["reputation"] = current
            changed_reputations.add(npc_id)
            outcomes.append(
                {
                    "type": "npc_reputation_changed",
                    "npc_id": npc_id,
                    "npc_name": npc.get("name", npc_id),
                    "previous": previous,
                    "delta": current - previous,
                    "reputation": current,
                    "reason_key": reason,
                }
            )
    return outcomes


def settle_pending_interactions(
    state: dict[str, Any], outcomes: list[dict[str, Any]]
) -> None:
    """Close queued interactions only after the model has produced a turn."""

    pending = state.get("pending_interactions") or []
    state["pending_interactions"] = []
    for interaction in pending:
        npc_id = interaction.get("npc_id")
        npc = (state.get("npc_state") or {}).get(npc_id)
        if npc:
            npc["last_spoke_turn"] = int(state.get("revision") or 0)
        outcomes.append(
            {
                "type": "npc_initiative_resolved",
                "interaction_id": interaction.get("id"),
                "npc_id": npc_id,
                "npc_name": interaction.get("npc_name"),
            }
        )


def _record_location_visit(state: dict[str, Any]) -> None:
    location_id = state.get("location_id")
    if not location_id:
        return
    current_turn = int(state.get("revision") or 0)
    location = (state.setdefault("location_state", {})).setdefault(
        location_id,
        {"known": False, "visited_turns": [], "last_visited_turn": None, "scene_state": {}},
    )
    location["known"] = True
    visits = location.setdefault("visited_turns", [])
    if current_turn not in visits:
        visits.append(current_turn)
        del visits[:-20]
    location["last_visited_turn"] = current_turn


def _record_npc_presence(
    state: dict[str, Any],
    definition: dict[str, Any],
    narrative: str,
    dialogues: list[dict[str, str]],
) -> None:
    current_turn = int(state.get("revision") or 0)
    current_location = state.get("location_id")
    dialogue_speakers = {dialogue["speaker"] for dialogue in dialogues}
    names = {
        str(item.get("name")): item
        for item in (definition.get("npcs") or [])
        if item.get("name")
    }
    for npc_id, npc in (state.setdefault("npc_state", {})).items():
        name = str(npc.get("name") or names.get(npc_id, {}).get("name") or "")
        if not name or name not in narrative:
            continue
        npc["met"] = True
        npc["location_id"] = current_location
        npc["last_seen_turn"] = current_turn
        if name in dialogue_speakers:
            npc["last_spoke_turn"] = current_turn


def choose_story_choice(
    state: dict[str, Any], definition: dict[str, Any], choice_id: object
) -> list[dict[str, Any]]:
    _require_capability(state, "choices")
    if not isinstance(choice_id, str):
        raise NarrativeRuleError("choose_story_choice requires choice_id")
    chapter_state = state["chapter"]
    if chapter_state is None or chapter_state["status"] != "active":
        raise NarrativeRuleError("there is no active chapter")
    chapter = _chapter(definition, chapter_state["id"])
    choice = next((item for item in chapter["choices"] if item["id"] == choice_id), None)
    if choice is None:
        raise NarrativeRuleError("choice is not available in the active chapter")
    if choice_id in chapter_state["resolved_choice_ids"]:
        raise NarrativeRuleError("choice was already resolved")
    chapter_state["resolved_choice_ids"].append(choice_id)
    outcomes = [{"type": "choose_story_choice", "chapter_id": chapter["id"], "choice_id": choice_id}]
    for effect in choice["effects"]:
        outcomes.extend(_apply_effect(state, definition, effect, cause=f"choice:{choice_id}"))
    return outcomes


def advance_chapter(state: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    _require_capability(state, "chapters")
    chapter_state = state["chapter"]
    if chapter_state is None or chapter_state["status"] != "active":
        raise NarrativeRuleError("there is no active chapter to advance")
    if not chapter_state["resolved_choice_ids"]:
        raise NarrativeRuleError("chapter cannot advance before resolving a choice")
    current = _chapter(definition, chapter_state["id"])
    if current["next_chapter_id"] is None:
        chapter_state["status"] = "completed"
        return {"type": "advance_chapter", "chapter_id": current["id"], "status": "completed"}
    state["chapter"] = {
        "id": current["next_chapter_id"],
        "status": "active",
        "resolved_choice_ids": [],
    }
    return {
        "type": "advance_chapter",
        "chapter_id": current["id"],
        "next_chapter_id": current["next_chapter_id"],
    }


def evaluate_endings(state: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    _require_capability(state, "endings")
    if state["ending"] is not None:
        raise NarrativeRuleError("ending is already locked")
    chapter = state["chapter"]
    if chapter is None or chapter["status"] != "completed":
        raise NarrativeRuleError("ending can only be evaluated after the final chapter")
    matched = [ending for ending in definition["story"]["endings"] if _matches(ending["when"], state)]
    if not matched:
        raise NarrativeRuleError("no ending matches the completed state")
    ending = min(matched, key=lambda item: (-item["priority"], item["id"]))
    state["ending"] = {
        "id": ending["id"],
        "kind": ending["kind"],
        "narrative_key": ending["narrative_key"],
    }
    return {"type": "lock_ending", **state["ending"]}


def available_choices(state: dict[str, Any], definition: dict[str, Any]) -> list[dict[str, str]]:
    chapter_state = state["chapter"]
    if state["ending"] is not None or chapter_state is None or chapter_state["status"] != "active":
        return []
    if "choices" not in state["ruleset"]["enabled_capabilities"]:
        return []
    chapter = _chapter(definition, chapter_state["id"])
    resolved = set(chapter_state["resolved_choice_ids"])
    return [
        {"id": choice["id"], "label": choice["label"]}
        for choice in chapter["choices"]
        if choice["id"] not in resolved
    ]


def planned_choice_commands(
    state: dict[str, Any], definition: dict[str, Any], choice_id: str
) -> list[dict[str, Any]]:
    if choice_id not in {choice["id"] for choice in available_choices(state, definition)}:
        raise NarrativeRuleError("choice is not available in the active chapter")
    chapter = _chapter(definition, state["chapter"]["id"])
    commands: list[dict[str, Any]] = [
        {"type": "choose_story_choice", "payload": {"choice_id": choice_id}},
        {"type": "advance_chapter", "payload": {}},
    ]
    if chapter["next_chapter_id"] is None:
        commands.append({"type": "evaluate_endings", "payload": {}})
    return commands


def _apply_effect(
    state: dict[str, Any], definition: dict[str, Any], effect: dict[str, Any], cause: str
) -> list[dict[str, Any]]:
    effect_type = effect["type"]
    if effect_type == "set_story_flag":
        flag = next(item for item in definition["story"]["flags"] if item["id"] == effect["flag_id"])
        if cause not in flag["writers"]:
            raise NarrativeRuleError("story flag cannot be written by this choice")
        state["flags"][flag["id"]] = effect["value"]
        return [{"type": "set_story_flag", "flag_id": flag["id"], "value": effect["value"], "cause": cause}]
    if effect_type == "apply_relationship_event":
        return [_apply_relationship_event(state, definition, effect["relationship_event_id"], cause)]
    if effect_type == "grant_resource":
        _change_inventory(state["inventory"], effect["resource_id"], effect["quantity"])
        return [{"type": "grant_resource", "resource_id": effect["resource_id"], "quantity": effect["quantity"], "cause": cause}]
    if effect_type == "set_route":
        if state["route"] is not None:
            raise NarrativeRuleError("route is already locked")
        state["route"] = {"id": effect["route_id"], "status": "locked"}
        return [{"type": "lock_route", "route_id": effect["route_id"], "cause": cause}]
    raise NarrativeRuleError("unsupported story effect")


def _apply_relationship_event(
    state: dict[str, Any], definition: dict[str, Any], event_id: str, cause: str
) -> dict[str, Any]:
    _require_capability(state, "relationships")
    event = next(item for item in definition["story"]["relationship_events"] if item["id"] == event_id)
    relationship_definition = next(
        item for item in definition["story"]["relationships"] if item["id"] == event["relationship_id"]
    )
    relationship = state["relationships"].get(event["relationship_id"])
    if relationship is None:
        raise NarrativeRuleError("relationship state is unavailable for this character")
    previous = relationship["applied_events"].get(event_id)
    chapter_id = state["chapter"]["id"] if state["chapter"] else None
    if previous is not None:
        if event["once_scope"] == "run":
            raise NarrativeRuleError("relationship event is once per run")
        if event["once_scope"] == "chapter" and previous["chapter_id"] == chapter_id:
            raise NarrativeRuleError("relationship event is once per chapter")
        if previous["cooldown_until_revision"] is not None and state["revision"] < previous["cooldown_until_revision"]:
            raise NarrativeRuleError("relationship event is cooling down")
    for dimension, delta in event["deltas"].items():
        bounds = relationship_definition["dimensions"][dimension]
        relationship["dimensions"][dimension] = max(
            bounds["min"], min(bounds["max"], relationship["dimensions"][dimension] + delta)
        )
    relationship["applied_events"][event_id] = {
        "turn_revision": state["revision"] + 1,
        "reason_key": event["reason_key"],
        "chapter_id": chapter_id,
        "cooldown_until_revision": state["revision"] + event["cooldown_turns"] + 1 if event["cooldown_turns"] else None,
    }
    return {"type": "apply_relationship_event", "relationship_event_id": event_id, "relationship_id": event["relationship_id"], "character_card_id": relationship_definition["character_card_id"], "deltas": event["deltas"], "reason_key": event["reason_key"], "cause": cause}


def _matches(condition: object, state: dict[str, Any]) -> bool:
    if not isinstance(condition, dict):
        raise NarrativeRuleError("ending condition must be an object")
    if "all" in condition:
        return isinstance(condition["all"], list) and all(_matches(item, state) for item in condition["all"])
    if "any" in condition:
        return isinstance(condition["any"], list) and any(_matches(item, state) for item in condition["any"])
    if "not" in condition:
        return not _matches(condition["not"], state)
    if set(condition) == {"flag", "equals"}:
        return state["flags"].get(condition["flag"]) is condition["equals"]
    if set(condition) == {"route"}:
        return state["route"] is not None and state["route"]["id"] == condition["route"]
    if set(condition) == {"relationship", "dimension", "at_least"}:
        relation = state["relationships"].get(condition["relationship"])
        return relation is not None and relation["dimensions"].get(condition["dimension"], -101) >= condition["at_least"]
    raise NarrativeRuleError("unsupported ending condition")


def _chapter(definition: dict[str, Any], chapter_id: str) -> dict[str, Any]:
    return next(chapter for chapter in definition["story"]["chapters"] if chapter["id"] == chapter_id)


def _require_capability(state: dict[str, Any], capability: str) -> None:
    if capability not in state["ruleset"]["enabled_capabilities"]:
        raise NarrativeRuleError(f"ruleset does not enable {capability}")


def _require_unique(items: list[dict[str, Any]], name: str) -> None:
    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        raise NarrativeRuleError(f"{name} ids must be unique")


def _validate_effect(effect: dict[str, Any], choice_id: str, flag_ids: set[str], relationship_event_ids: set[str], route_ids: set[str], resource_ids: set[str]) -> None:
    effect_type = effect["type"]
    if effect_type == "set_story_flag" and effect.get("flag_id") in flag_ids and isinstance(effect.get("value"), bool):
        return
    if effect_type == "apply_relationship_event" and effect.get("relationship_event_id") in relationship_event_ids:
        return
    if effect_type == "grant_resource" and effect.get("resource_id") in resource_ids and isinstance(effect.get("quantity"), int):
        return
    if effect_type == "set_route" and effect.get("route_id") in route_ids:
        return
    raise NarrativeRuleError(f"choice {choice_id} has an invalid {effect_type} effect")


def _change_inventory(inventory: list[dict[str, Any]], item_id: str, delta: int) -> None:
    current = next((item for item in inventory if item["id"] == item_id), None)
    if current is None:
        inventory.append({"id": item_id, "quantity": delta})
    else:
        current["quantity"] += delta
