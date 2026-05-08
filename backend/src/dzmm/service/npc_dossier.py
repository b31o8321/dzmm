"""NPC dossier formatters for key_facts injection.

`_format_npc_dossier` produces the 3-5 line block used for pinned + recalled
NPCs (full dossier path); `_format_npc_short` is the one-liner for
recently-seen NPCs. Both honor v0.11's `revealed_json` mask — fields not yet
revealed to the player are explicitly *not* printed with their value, only
flagged as hidden so the GM can choose to surface them organically through
narrative.

Extracted from `service/game.py` (v0.1.6 refactor).
"""
import json

from dzmm.db.models import NPC


def _npc_revealed(npc: NPC) -> dict[str, bool]:
    """Decode npc.revealed_json with safe fallback. ``name`` is always revealed
    — GM has to be able to refer to the NPC even when other fields are hidden.
    """
    try:
        revealed = json.loads(npc.revealed_json or '{"name": true}')
        if not isinstance(revealed, dict):
            revealed = {}
    except (TypeError, ValueError):
        revealed = {}
    revealed["name"] = True  # always — anchor for GM reference
    return revealed


def _format_npc_dossier(npc: NPC) -> str:
    """Full dossier block for pinned/recalled NPCs.

    v0.11: fields not present in ``npc.revealed_json`` are NOT printed with
    their actual value — instead the GM is told the field exists but is
    unrevealed so it can surface organically through narrative.
    """
    revealed = _npc_revealed(npc)

    archetype = (npc.archetype or "").strip()
    state = (npc.state or "").strip() or "未知"
    # Gender is treated as fundamental to identity (along with name) — always
    # surfaced to the GM regardless of revealed_json. Empty/legacy values
    # produce no marker.
    gender = (npc.gender or "").strip()
    gender_marker = {"male": "♂", "female": "♀"}.get(gender, "")
    head = f"- {npc.name}"
    if gender_marker:
        head += f"({gender_marker})"
    if archetype and revealed.get("archetype"):
        head += f" [{archetype}]"
    if revealed.get("state"):
        head += f" 状态：{state}"

    lines: list[str] = [head]

    purpose = (npc.purpose or "").strip()
    if purpose and revealed.get("purpose"):
        lines.append(f"  动机：{purpose}")

    affinity_parts: list[str] = []
    if revealed.get("favor"):
        affinity_parts.append(f"好感{npc.favor:+d}")
    if revealed.get("affinity"):
        try:
            affinity = json.loads(npc.affinity_json or "{}")
        except (TypeError, ValueError):
            affinity = {}
        if isinstance(affinity, dict):
            for axis, val in affinity.items():
                if isinstance(val, (int, float)):
                    affinity_parts.append(f"{axis}{int(val):+d}")
    if affinity_parts:
        lines.append("  " + "｜".join(affinity_parts))

    try:
        notes = json.loads(npc.notes_json or "[]")
    except (TypeError, ValueError):
        notes = []
    if isinstance(notes, list) and notes:
        # Notes are GM-authored shorthand like "分享了童年阴影" — internal
        # continuity markers, not raw NPC fields, so we don't gate them on
        # revealed_json. They're written by the GM after a scene the player
        # just witnessed.
        last = notes[-1]
        text = ""
        if isinstance(last, dict):
            text = str(last.get("text", "")).strip()
        elif isinstance(last, str):
            text = last.strip()
        if text:
            lines.append(f"  最近：{text}")
    elif npc.description and revealed.get("description"):
        desc = npc.description.strip()
        if desc:
            lines.append(f"  备注：{desc[:60]}")

    # Surface a list of fields that exist but are NOT yet revealed. Lets the
    # GM know there's hidden setting around this NPC it can unveil — without
    # leaking the values.
    hidden_fields: list[str] = []
    if (npc.description or "").strip() and not revealed.get("description"):
        hidden_fields.append("description")
    if (npc.purpose or "").strip() and not revealed.get("purpose"):
        hidden_fields.append("purpose")
    if (npc.archetype or "").strip() and not revealed.get("archetype"):
        hidden_fields.append("archetype")
    if (npc.state or "").strip() and not revealed.get("state"):
        hidden_fields.append("state")
    if not revealed.get("favor") and npc.favor != 0:
        hidden_fields.append("favor")
    if not revealed.get("affinity"):
        try:
            aff = json.loads(npc.affinity_json or "{}")
        except (TypeError, ValueError):
            aff = {}
        if isinstance(aff, dict) and aff:
            hidden_fields.append("affinity")
    if not revealed.get("emotion"):
        try:
            emo = json.loads(npc.emotion_json or "{}")
        except (TypeError, ValueError):
            emo = {}
        if isinstance(emo, dict) and emo:
            hidden_fields.append("emotion")
    if hidden_fields:
        lines.append(
            "  [未揭示：" + "/".join(hidden_fields)
            + " — 玩家尚未通过对话或调查获悉，请勿在叙述中直接说出]"
        )

    return "\n".join(lines)


def _format_npc_short(npc: NPC) -> str:
    """One-line summary for recently-seen NPCs (legacy compact format).

    v0.11: only print fields the player has already learned. Description goes
    verbatim if revealed; favor and state are hidden behind '?' otherwise so
    the GM still knows the NPC exists without leaking the value.
    """
    revealed = _npc_revealed(npc)
    favor_str = f"{npc.favor:+d}" if revealed.get("favor") else "??"
    state_str = npc.state if revealed.get("state") else "??"
    desc = (npc.description or "").strip() if revealed.get("description") else ""
    gender_marker = {"male": "♂", "female": "♀"}.get((npc.gender or "").strip(), "")
    name_with_gender = f"{npc.name}({gender_marker})" if gender_marker else npc.name
    parts = f"- {name_with_gender}（好感{favor_str}，状态：{state_str}）"
    if desc:
        parts += desc[:40]
    return parts
