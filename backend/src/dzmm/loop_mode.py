"""Loop capability (v1.4.0 M2) — rewind semantics and drift directives.

The anchor snapshot is engine-managed: on ``start_loop`` the engine freezes a
deep copy of the run state. ``rewind_to_anchor`` restores it while merging
back the cross-loop layers (loop_memory, npc deja_vu) and bumping the loop
count. Loop-triggered rewinds never touch the turn rollback machinery.
"""

from __future__ import annotations

import copy
from typing import Any

DEJA_VU_MAX = 100
DEJA_VU_STEP = 15


def initial_loop_state(definition: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    """Build the loop block when the world declares a loop configuration."""

    config = definition.get("loop_config")
    if not isinstance(config, dict) or not config.get("max_loops"):
        return None
    return {
        "count": 1,
        "max_loops": max(1, min(100, int(config.get("max_loops") or 1))),
        "anchor_turn": 0,
        "trigger": config.get("trigger") or ["time"],
        "deja_vu": {
            npc_id: 0 for npc_id in (state.get("npc_state") or {})
        },
    }


def anchor_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """Freeze the anchor: everything except loop bookkeeping itself."""

    snapshot = copy.deepcopy(state)
    snapshot.pop("loop", None)
    return snapshot


def rewind_to_anchor(
    state: dict[str, Any], anchor: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Restore the anchor while merging cross-loop layers.

    Returns (new_state, notes). Preserved across the rewind: loop_memory
    (knowledge/summaries/count), npc deja_vu. Wiped: everything ephemeral
    (narrative_context, npc dialogue memory, inventory/events unless declared
    persists_across_loops).
    """
    new_state = copy.deepcopy(anchor)
    loop = copy.deepcopy(state.get("loop") or {})
    loop["count"] = int(loop.get("count") or 1) + 1
    new_state["loop"] = loop

    notes: list[str] = []

    # loop_memory: knowledge/summaries/count survive (memory layer 2+3)
    old_memory = state.get("loop_memory") or {}
    new_memory = new_state.get("loop_memory") or initial_memory_fallback()
    knowledge = old_memory.get("knowledge") or []
    summaries = old_memory.get("summaries") or []
    if knowledge:
        new_memory["knowledge"] = knowledge
        notes.append(f"跨循环记忆保留：{len(knowledge)} 条")
    if summaries:
        new_memory["summaries"] = summaries
    new_memory["count"] = loop["count"]
    new_state["loop_memory"] = new_memory

    # NPC deja_vu survives (meta-impression, not memory)
    old_deja = (state.get("loop") or {}).get("deja_vu") or {}
    npc_state = new_state.get("npc_state") or {}
    for npc_id, npc in npc_state.items():
        npc["deja_vu"] = min(DEJA_VU_MAX, int(old_deja.get(npc_id) or 0))

    # ephemeral wipe
    new_state["narrative_context"] = {
        "run_seed": new_state.get("narrative_context", {}).get("run_seed", ""),
        "turn_index": 0,
        "recent_turns": [],
        "current_hook": {"key": "", "directive": "", "turn": "0"},
    }
    new_state["revision"] = int(anchor.get("revision") or 0) + 1
    new_state["ending"] = None
    new_state["combat"] = {"participants": {}}
    return new_state, notes


def initial_memory_fallback() -> dict[str, Any]:
    return {"count": 1, "knowledge": [], "summaries": []}


def bump_deja_vu(state: dict[str, Any], npc_id: str, step: int = DEJA_VU_STEP) -> None:
    """Accumulate NPC meta-impression when the player repeats loop behaviour."""

    loop = state.get("loop")
    if not isinstance(loop, dict):
        return
    deja = loop.setdefault("deja_vu", {})
    deja[npc_id] = min(DEJA_VU_MAX, int(deja.get(npc_id) or 0) + step)


def should_trigger_death_rewind(state: dict[str, Any]) -> bool:
    """True when a bad/hidden ending should rewind instead of locking."""

    loop = state.get("loop")
    if not isinstance(loop, dict):
        return False
    ending = state.get("ending") or {}
    if ending.get("kind") not in {"bad", "hidden"}:
        return False
    triggers = loop.get("trigger") or []
    if "death" not in triggers:
        return False
    return int(loop.get("count") or 1) < int(loop.get("max_loops") or 1)


def drift_directive(loop_count: int, base: str) -> str:
    """Escalating drift direction for replayed scenes as loops accumulate."""

    if loop_count <= 1:
        return base
    escalations = [
        "NPC 的情绪明显更紧张了，对话中透出不安",
        "NPC 开始出现细微的既视感表现——皱眉、迟疑、盯着玩家看",
        "世界的细节开始出现循环裂痕：重复的对话被 NPC 突然打断",
        "紧张感达到顶点：NPC 的反应几乎预示了玩家的动作",
    ]
    idx = min(loop_count - 2, len(escalations) - 1)
    return f"{base}；本轮漂移：{escalations[idx]}"
