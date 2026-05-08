"""Tests for `_effective_reveals` and the dossier formatters that consume it.

Bug context: threshold-based auto-reveal rules (last_seen_turn>0 → description
visible, |favor|>=30 → purpose visible, etc.) used to live only in the
frontend serializer (`_npc_to_dict` in routes_sessions/_common.py). The GM
dossier builder (`_format_npc_dossier`) read raw `revealed_json` directly, so
an NPC the player had clearly already met (last_seen_turn=5, favor=+30) was
still being framed to the GM as "[未揭示：description/purpose/...]". GM then
kept "hinting" at things the player already knew.

Fix: extract the overlay logic into `_effective_reveals` and have both call
sites use it.
"""
import json

import pytest

from dzmm.db.models import NPC
from dzmm.service.npc_dossier import (
    _effective_reveals,
    _format_npc_dossier,
    _format_npc_short,
)


def _make_npc(
    *,
    favor: int = 0,
    last_seen_turn: int = 0,
    description: str = "",
    purpose: str = "",
    archetype: str = "",
    state: str = "未知",
    revealed_json: str = '{"name": true}',
    affinity_json: str = "{}",
    emotion_json: str = "{}",
) -> NPC:
    return NPC(
        session_id=1,
        name="测试 NPC",
        gender="",
        description=description,
        favor=favor,
        state=state,
        last_seen_turn=last_seen_turn,
        notes_json="[]",
        purpose=purpose,
        archetype=archetype,
        affinity_json=affinity_json,
        emotion_json=emotion_json,
        revealed_json=revealed_json,
        pinned=False,
    )


# ── _effective_reveals: threshold rules ──────────────────────────────


def test_effective_reveals_offstage_npc_keeps_description_hidden():
    """Never appeared (last_seen_turn=0) → description stays hidden even if
    it has content. Players haven't seen the NPC yet."""
    npc = _make_npc(description="干净利落的女打手", last_seen_turn=0)
    revealed = _effective_reveals(npc)
    assert revealed.get("description") is not True
    # name is always on
    assert revealed["name"] is True


def test_effective_reveals_seen_npc_reveals_observable_fields():
    """last_seen_turn>0 → description/state/favor auto-revealed."""
    npc = _make_npc(description="干净利落的女打手", last_seen_turn=3)
    revealed = _effective_reveals(npc)
    assert revealed["description"] is True
    assert revealed["state"] is True
    assert revealed["favor"] is True


def test_effective_reveals_archetype_at_favor_threshold():
    """|favor|>=20 OR (seen + has archetype) → archetype revealed."""
    npc = _make_npc(favor=25, last_seen_turn=5, archetype="对手")
    revealed = _effective_reveals(npc)
    assert revealed["archetype"] is True


def test_effective_reveals_archetype_seen_with_archetype_text():
    """Even at favor=0, just being seen + having an archetype string → revealed."""
    npc = _make_npc(favor=0, last_seen_turn=2, archetype="导师")
    revealed = _effective_reveals(npc)
    assert revealed["archetype"] is True


def test_effective_reveals_archetype_below_threshold_not_seen():
    """Low favor + not seen + no archetype text → archetype stays hidden."""
    npc = _make_npc(favor=5, last_seen_turn=0, archetype="")
    revealed = _effective_reveals(npc)
    assert revealed.get("archetype") is not True


def test_effective_reveals_purpose_at_favor_threshold():
    """|favor|>=30 → purpose revealed."""
    npc = _make_npc(favor=30, last_seen_turn=5, purpose="找出真凶")
    revealed = _effective_reveals(npc)
    assert revealed["purpose"] is True


def test_effective_reveals_purpose_below_threshold_hidden():
    npc = _make_npc(favor=15, last_seen_turn=5, purpose="找出真凶")
    revealed = _effective_reveals(npc)
    assert revealed.get("purpose") is not True


def test_effective_reveals_explicit_false_overrides_threshold():
    """If revealed_json explicitly says description=false, threshold rules
    must NOT flip it to true. setdefault preserves explicit values; this is
    the GM/user's escape hatch to forcibly hide a field."""
    npc = _make_npc(
        description="秘密身份",
        last_seen_turn=10,
        revealed_json='{"name": true, "description": false}',
    )
    revealed = _effective_reveals(npc)
    assert revealed["description"] is False
    # Other auto-reveals still apply
    assert revealed["state"] is True
    assert revealed["favor"] is True


def test_effective_reveals_name_always_true_even_if_stored_false():
    """name must always be true so the GM can refer to the NPC at all."""
    npc = _make_npc(revealed_json='{"name": false}')
    revealed = _effective_reveals(npc)
    assert revealed["name"] is True


def test_effective_reveals_handles_malformed_revealed_json():
    """Garbage in revealed_json shouldn't crash; we fall back to name-only."""
    npc = _make_npc(revealed_json="not-json")
    revealed = _effective_reveals(npc)
    assert revealed["name"] is True


# ── _format_npc_dossier: dossier prompt block respects thresholds ──


def test_dossier_offstage_npc_marks_description_unrevealed():
    """An NPC with description but last_seen_turn=0 should produce the
    "[未揭示：description ...]" hint to the GM."""
    npc = _make_npc(
        description="干净利落的女打手",
        last_seen_turn=0,
        favor=0,
    )
    out = _format_npc_dossier(npc)
    assert "[未揭示：" in out
    assert "description" in out
    # The actual description value must NOT leak.
    assert "干净利落" not in out


def test_dossier_seen_npc_does_not_mark_description_unrevealed():
    """The bug: NPC has been on stage (last_seen_turn=3) so description is
    effectively revealed — dossier must NOT include the "[未揭示" warning
    for description."""
    npc = _make_npc(
        description="干净利落的女打手",
        last_seen_turn=3,
        favor=10,
    )
    out = _format_npc_dossier(npc)
    # The "[未揭示" block must not include description.
    if "[未揭示：" in out:
        # If a hidden block exists for some other field, ensure description
        # isn't in it.
        hidden_line = [ln for ln in out.split("\n") if "[未揭示：" in ln][0]
        assert "description" not in hidden_line
    # And the description value should appear somewhere (备注: ...)
    assert "干净利落" in out


def test_dossier_high_favor_reveals_purpose():
    """favor=+30 + purpose set → purpose surfaces in dossier (动机：...)."""
    npc = _make_npc(
        description="某 NPC",
        last_seen_turn=5,
        favor=30,
        purpose="找出真凶",
        archetype="对手",
    )
    out = _format_npc_dossier(npc)
    assert "动机：找出真凶" in out
    # archetype revealed via favor>=20 too
    assert "[对手]" in out


def test_dossier_explicit_false_overrides_threshold():
    """User/GM explicitly hid description=false → even with last_seen_turn=10
    the dossier must still mark description as unrevealed."""
    npc = _make_npc(
        description="秘密身份",
        last_seen_turn=10,
        favor=5,
        revealed_json='{"name": true, "description": false}',
    )
    out = _format_npc_dossier(npc)
    assert "[未揭示：" in out
    hidden_line = [ln for ln in out.split("\n") if "[未揭示：" in ln][0]
    assert "description" in hidden_line
    assert "秘密身份" not in out


# ── _format_npc_short: one-liner respects thresholds too ──────────


def test_short_offstage_npc_masks_favor_and_state():
    """last_seen_turn=0 → favor/state shown as ?? in the short form."""
    npc = _make_npc(favor=10, state="戒备", last_seen_turn=0)
    out = _format_npc_short(npc)
    assert "好感??" in out
    assert "状态：??" in out


def test_short_seen_npc_shows_real_favor_and_state():
    """Once seen, the short form must show real favor/state — matching the
    frontend, no more "??" mismatch."""
    npc = _make_npc(favor=10, state="戒备", last_seen_turn=3)
    out = _format_npc_short(npc)
    assert "好感+10" in out
    assert "状态：戒备" in out


# ── _npc_to_dict: frontend serializer goes through the same helper ──


def test_npc_to_dict_uses_effective_reveals():
    """Sanity check that the frontend serializer and the dossier builder now
    return the same reveal map for the same NPC."""
    from dzmm.api.routes_sessions._common import _npc_to_dict

    npc = _make_npc(
        description="干净利落的女打手",
        last_seen_turn=3,
        favor=25,
        archetype="对手",
        purpose="找出真凶",
    )
    d = _npc_to_dict(npc)
    assert d["revealed"]["description"] is True
    assert d["revealed"]["state"] is True
    assert d["revealed"]["favor"] is True
    assert d["revealed"]["archetype"] is True
    # favor=25 < 30 → purpose stays hidden
    assert d["revealed"].get("purpose") is not True

    # And the dossier builder agrees.
    revealed = _effective_reveals(npc)
    for k in ("description", "state", "favor", "archetype"):
        assert revealed[k] == d["revealed"][k]
