"""Tests for world_brief prompt polish (Goals A, B, C)."""

from dzmm.prompts.wizard_world_brief import (
    _GENRE_CONFLICT_HINTS,
    build_world_brief_messages,
)
from dzmm.service.wizard import _render_brief_md


# ---------------------------------------------------------------------------
# Goal A — genre-specific conflict hints injected into user message
# ---------------------------------------------------------------------------

def test_known_genre_injects_genre_hint():
    """A known genre should inject the matching hint into the user message."""
    msgs = build_world_brief_messages("悬疑探案", "2091年反乌托邦城市")
    user_content = msgs[-1].content
    assert "当下危机提示" in user_content
    assert _GENRE_CONFLICT_HINTS["悬疑探案"] in user_content


def test_unknown_genre_no_hint_injected():
    """An unknown / custom genre should not add a hint block."""
    msgs = build_world_brief_messages("自定义", "玩家自定义主题")
    user_content = msgs[-1].content
    assert "当下危机提示" not in user_content


def test_all_5_canonical_genres_have_hints():
    """At least the five most common canonical genres must be present in the hint dict."""
    required = {"悬疑探案", "政治阴谋", "奇幻冒险", "赛博朋克", "恐怖求生"}
    missing = required - set(_GENRE_CONFLICT_HINTS.keys())
    assert not missing, f"Missing genre hints for: {missing}"


# ---------------------------------------------------------------------------
# Goal B — conflict spec in system message mentions NPC + location requirement
# ---------------------------------------------------------------------------

def test_conflict_spec_mentions_npc_and_location_requirement():
    """System prompt must instruct the model to name an NPC and a location."""
    msgs = build_world_brief_messages("奇幻冒险", "魔法枯竭")
    system_content = msgs[0].content
    # Both the NPC and location constraint indicators should be present
    assert "NPC" in system_content or "人物名" in system_content
    assert "地点" in system_content or "建筑名" in system_content


# ---------------------------------------------------------------------------
# Goal C — _render_brief_md renders ⚡ 当下危机 section
# ---------------------------------------------------------------------------

def test_render_brief_md_has_当下危机_section():
    """Rendered markdown must contain the dedicated 当下危机 section header."""
    md = _render_brief_md("测试世界", "2091年的新香港", "侦探陈墨衍在码头发现了尸体。")
    assert "## ⚡ 当下危机" in md
    assert "侦探陈墨衍在码头发现了尸体" in md
    # Old heading must be gone
    assert "## 核心冲突" not in md


def test_render_brief_md_structure():
    """Full rendered markdown should follow the specified structure."""
    name = "钢铁迷雾"
    setting = "2091年的反乌托邦城市"
    conflict = "侦探李明在北区仓库发现了一批失踪档案。"
    md = _render_brief_md(name, setting, conflict)

    assert md.startswith(f"# {name}")
    assert "## 时代背景" in md
    assert setting in md
    assert "## ⚡ 当下危机" in md
    assert conflict in md
    assert "PC 第 1 章" in md


# ---------------------------------------------------------------------------
# Structural — JSON schema preserved (parse still works on valid JSON)
# ---------------------------------------------------------------------------

def test_world_brief_json_structure_preserved():
    """build_world_brief_messages must still accept genre+theme without error."""
    msgs = build_world_brief_messages("赛博朋克", "企业战争")
    assert len(msgs) == 2
    assert msgs[0].role == "system"
    assert msgs[1].role == "user"
    # The user message must still contain the genre and theme
    assert "赛博朋克" in msgs[1].content
    assert "企业战争" in msgs[1].content
