"""Three-layer memory infrastructure for loop genres (v1.4.0 M0).

Layer 1 (ephemeral):    narrative_context.recent_turns / npc_state — wiped on rewind.
Layer 2 (persistent):   loop_knowledge — engine-whitelisted facts that survive
                        rewinds; the GM is told only these verified facts.
Layer 3 (per-loop):     loop_summaries — one ~200-char digest per completed loop,
                        appended on rewind, injected into the GM payload.

All writes go through engine-whitelisted commands (`discover`); the model can
never write loop memory directly.
"""

from __future__ import annotations

import re
from typing import Any

KNOWLEDGE_TEXT_MAX = 200
KNOWLEDGE_MAX_ITEMS = 24


def initial_loop_memory() -> dict[str, Any]:
    """Initial loop-memory block for worlds that enable the loop capability."""

    return {
        "count": 1,
        "knowledge": [],
        "summaries": [],
    }


def discover_knowledge(
    memory: dict[str, Any], knowledge_id: str, text: str, turn: int
) -> tuple[dict[str, Any] | None, list[str]]:
    """Add a whitelisted cross-loop fact. Returns (new_entry, repairs).

    Deduplicates by id; clamps text length; caps item count.
    """
    knowledge_id = str(knowledge_id or "").strip()
    text = str(text or "").strip()[:KNOWLEDGE_TEXT_MAX]
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", knowledge_id):
        return None, [f"discover: 非法知识 id {knowledge_id!r}，已忽略"]
    if not text:
        return None, ["discover: 缺少内容，已忽略"]
    knowledge = memory.setdefault("knowledge", [])
    if any(item["id"] == knowledge_id for item in knowledge):
        for item in knowledge:
            if item["id"] == knowledge_id:
                item["text"] = text
                item["discovered_turn"] = turn
        return {"id": knowledge_id, "text": text, "discovered_turn": turn}, [
            f"discover: 知识 {knowledge_id} 已更新"
        ]
    if len(knowledge) >= KNOWLEDGE_MAX_ITEMS:
        return None, ["discover: 知识已达上限，已忽略"]
    entry = {"id": knowledge_id, "text": text, "discovered_turn": turn}
    knowledge.append(entry)
    return entry, []


def rewind_memory(memory: dict[str, Any]) -> dict[str, Any]:
    """Advance the memory block across a loop boundary.

    Ephemeral layer is wiped by the caller (state restoration); here we bump the
    loop counter and keep knowledge/summaries intact.
    """
    memory["count"] = int(memory.get("count") or 1) + 1
    memory.setdefault("knowledge", [])
    memory.setdefault("summaries", [])
    return memory


def append_loop_summary(memory: dict[str, Any], loop_no: int, summary: str) -> None:
    """Store a per-loop digest (~200 chars, clamped)."""
    summaries = memory.setdefault("summaries", [])
    if any(item.get("loop_no") == loop_no for item in summaries):
        return
    summaries.append(
        {"loop_no": loop_no, "summary": str(summary or "").strip()[:200]}
    )


def loop_memories_for_prompt(memory: dict[str, Any]) -> list[dict[str, Any]]:
    """Whitelisted cross-loop facts injected into the GM payload."""
    return [
        {"id": item["id"], "text": item["text"]}
        for item in memory.get("knowledge") or []
    ]


def loop_summaries_for_prompt(memory: dict[str, Any], limit: int = 2) -> list[dict[str, Any]]:
    """Most recent per-loop digests injected into the GM payload."""
    summaries = sorted(
        memory.get("summaries") or [], key=lambda item: item.get("loop_no") or 0
    )
    return [
        {"loop_no": item["loop_no"], "summary": item["summary"]}
        for item in summaries[-limit:]
    ]
