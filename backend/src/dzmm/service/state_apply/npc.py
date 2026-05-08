"""NPC-related state_apply handlers.

Carved out of `_impl.py` in r3-a. Covers:
  - <npc_update> handler + progressive-reveal bookkeeping

The dispatcher (`apply_tags` in `_impl.py`) imports the handlers below;
shared helpers (e.g. `_normalize_for_dedup`) remain in `_impl.py`.
"""

import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import NPC
from dzmm.parsing.repair import parse_loose_json

log = logging.getLogger(__name__)


# v0.11 progressive reveal: only these field names can be marked revealed.
# Unknown reveal targets are silently ignored. "name" is always revealed
# implicitly (defaulted in revealed_json), but listing it here is harmless.
_NPC_REVEALABLE_FIELDS = frozenset({
    "name", "description", "purpose", "archetype",
    "state", "favor", "affinity", "emotion",
})

_REVEAL_SPLIT_RE = re.compile(r"[,\s]+")


_GENDER_VALID = {"male", "female"}
_GENDER_ALIAS = {
    "男": "male", "男性": "male", "m": "male", "boy": "male", "man": "male",
    "女": "female", "女性": "female", "f": "female", "girl": "female", "woman": "female",
}


def _normalize_gender_str(raw: object) -> str:
    """Coerce a payload gender value to "male"/"female"/"" — same enum as
    `service.wizard._normalize_gender`. Duplicated locally to avoid a
    state_apply→service.wizard import (state_apply is the lower layer)."""
    if not raw:
        return ""
    s = str(raw).strip().lower()
    if not s:
        return ""
    if s in _GENDER_VALID:
        return s
    return _GENDER_ALIAS.get(s, "")


def _auto_reveal_for_create(payload: dict) -> dict:
    """When creating a new NPC, fields whose value is being set in the same
    payload (description / state / archetype / purpose / favor_delta / etc.)
    should be auto-marked revealed=true — the GM is writing them now, so the
    player has just seen them.

    name is always revealed (the GM has to name an NPC for them to exist)."""
    revealed = {"name": True}
    for f in ("description", "state", "archetype", "purpose"):
        if payload.get(f):
            revealed[f] = True
    if payload.get("favor_delta") is not None:
        revealed["favor"] = True
    if payload.get("affinity"):
        revealed["affinity"] = True
    if payload.get("emotion"):
        revealed["emotion"] = True
    return revealed


def _parse_reveal_attr(reveal_str: str) -> list[str]:
    """Split a reveal="..." attribute into a list of recognised field names.
    Accepts commas, whitespace, or both as separators. Unknown fields are
    silently dropped."""
    if not reveal_str:
        return []
    fields = [f.strip() for f in _REVEAL_SPLIT_RE.split(reveal_str) if f.strip()]
    return [f for f in fields if f in _NPC_REVEALABLE_FIELDS]


async def _apply_npc_update(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict[str, str],
    raw: str,
) -> None:
    # Merge attrs with body JSON. Body wins on conflict (GM is more deliberate
    # when it serialises a JSON payload than when it inlines attrs).
    payload: dict = {}
    payload.update({k: v for k, v in (attrs or {}).items()})
    body_payload = parse_loose_json(raw)
    if body_payload:
        payload.update(body_payload)

    name = payload.get("name")
    if not name:
        return
    name = str(name).strip()
    if not name:
        return

    npc = (
        await session.execute(
            select(NPC).where(NPC.session_id == session_id, NPC.name == name)
        )
    ).scalar_one_or_none()

    reveal_fields = _parse_reveal_attr(str(payload.get("reveal", "")))

    is_create = npc is None
    if is_create:
        # Special case: a payload that ONLY carries a reveal=... directive
        # against a non-existent NPC is a silent no-op. The intent is
        # "unlock previously-hidden fields"; without an existing NPC, there's
        # nothing to unlock and we don't fabricate a stub from a typo.
        # Any other shape (name only, name + value fields, etc.) creates.
        keys_other_than_name_and_reveal = [
            k for k in payload.keys() if k not in ("name", "reveal")
        ]
        if reveal_fields and not keys_other_than_name_and_reveal:
            return

        npc = NPC(
            session_id=session_id,
            name=name,
            gender=_normalize_gender_str(payload.get("gender")),
            description=payload.get("description", ""),
            favor=0,
            state=payload.get("state", "未知"),
            last_seen_turn=current_turn,
            notes_json="[]",
            purpose="",
            archetype="",
            affinity_json="{}",
            pinned=False,
            revealed_json=json.dumps(
                _auto_reveal_for_create(payload), ensure_ascii=False
            ),
        )
        session.add(npc)

    favor_delta_raw = payload.get("favor_delta", 0)
    favor_delta_num = 0
    if isinstance(favor_delta_raw, bool):
        favor_delta_num = 0
    elif isinstance(favor_delta_raw, (int, float)):
        favor_delta_num = int(favor_delta_raw)
    elif isinstance(favor_delta_raw, str):
        # attrs always parse as strings; tolerate an integer literal.
        try:
            favor_delta_num = int(favor_delta_raw)
        except ValueError:
            favor_delta_num = 0
    if favor_delta_num:
        npc.favor += favor_delta_num
    if "state" in payload and payload["state"] is not None:
        npc.state = str(payload["state"])
    if "description" in payload and not npc.description:
        npc.description = str(payload["description"])

    purpose = payload.get("purpose")
    if purpose is not None:
        npc.purpose = str(purpose)

    archetype = payload.get("archetype")
    if archetype is not None:
        npc.archetype = str(archetype)

    # Gender — only set if currently empty (legacy data); never overwrite an
    # existing male/female assignment from a later GM emit, since flipping
    # gender mid-story corrupts continuity.
    if not (npc.gender or "").strip():
        new_gender = _normalize_gender_str(payload.get("gender"))
        if new_gender:
            npc.gender = new_gender

    affinity_delta = payload.get("affinity")
    if isinstance(affinity_delta, dict):
        existing = json.loads(npc.affinity_json or "{}")
        if not isinstance(existing, dict):
            existing = {}
        for axis, delta in affinity_delta.items():
            if not isinstance(delta, (int, float)):
                continue
            axis_key = str(axis)
            existing[axis_key] = int(existing.get(axis_key, 0)) + int(delta)
        npc.affinity_json = json.dumps(existing, ensure_ascii=False)

    emotion_delta = payload.get("emotion")
    if isinstance(emotion_delta, dict):
        emotions = json.loads(npc.emotion_json or "{}")
        if not isinstance(emotions, dict):
            emotions = {}
        for axis, delta in emotion_delta.items():
            if axis not in ("anger", "love", "fear", "respect", "jealousy"):
                continue
            if not isinstance(delta, (int, float)):
                continue
            new_val = int(emotions.get(axis, 0) + delta)
            emotions[axis] = max(0, min(100, new_val))
        npc.emotion_json = json.dumps(emotions, ensure_ascii=False)

    # v0.2.6: scene binding — sets or clears NPC's current location.
    if "location" in payload:
        loc_val = payload["location"]
        if isinstance(loc_val, str):
            npc.current_location = loc_val.strip() or None
        else:
            npc.current_location = None

    note = payload.get("note")
    if note:
        notes = json.loads(npc.notes_json or "[]")
        notes.append({"turn": current_turn, "text": str(note)})
        npc.notes_json = json.dumps(notes, ensure_ascii=False)
    npc.last_seen_turn = current_turn

    # Progressive reveal bookkeeping. Two sources merge into revealed_json:
    #   1. fields that have a concrete value in this payload
    #      (auto-revealed: GM just wrote them, so the player has seen them)
    #   2. names listed in the reveal="..." attribute
    # Both add to the existing set; never clear what was previously revealed.
    try:
        revealed = json.loads(npc.revealed_json or '{"name": true}')
        if not isinstance(revealed, dict):
            revealed = {"name": True}
    except (TypeError, ValueError):
        revealed = {"name": True}

    # Auto-reveal: any field with a meaningful value in this update was visible
    # to the player when the GM emitted it — mark revealed. (For updates only;
    # create path already auto-revealed via _auto_reveal_for_create above.)
    if not is_create:
        if payload.get("description"):
            revealed["description"] = True
        if payload.get("state") not in (None, ""):
            revealed["state"] = True
        if payload.get("archetype"):
            revealed["archetype"] = True
        if payload.get("purpose"):
            revealed["purpose"] = True
        if payload.get("favor_delta") is not None and favor_delta_num:
            revealed["favor"] = True
        if payload.get("affinity"):
            revealed["affinity"] = True
        if payload.get("emotion"):
            revealed["emotion"] = True

    for f in reveal_fields:
        revealed[f] = True

    npc.revealed_json = json.dumps(revealed, ensure_ascii=False)
