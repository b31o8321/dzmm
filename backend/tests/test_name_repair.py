"""Unit tests for the PC-name drift repair pass that runs over GM output
before persistence (see _repair_pc_name in service/game.py)."""
from dzmm.service.game import _repair_pc_name


def test_repair_self_intro_drift():
    text = (
        "<narrative>她问起。</narrative>"
        "<pc_action>我叫林峰，请多关照。</pc_action>"
    )
    out, n = _repair_pc_name(text, "Riku")
    assert "Riku" in out
    assert "林峰" not in out
    assert n == 1


def test_repair_skips_npc_say():
    # NPC named 林峰 introducing themselves inside <say> must NOT be touched —
    # that's NPC dialogue, not PC drift.
    text = '<say speaker="林峰">「我是林峰，你好。」</say>'
    out, n = _repair_pc_name(text, "Riku")
    assert "林峰" in out
    assert n == 0


def test_repair_preserves_correct_name():
    text = "<pc_action>我叫Riku。</pc_action>"
    out, n = _repair_pc_name(text, "Riku")
    assert n == 0
    assert out == text


def test_repair_multiple_drifts():
    text = (
        "<pc_action>我是云野。</pc_action>"
        "<narrative>...</narrative>"
        "<pc_action>叫我林峰即可。</pc_action>"
    )
    out, n = _repair_pc_name(text, "沈三川")
    assert "云野" not in out
    assert "林峰" not in out
    assert out.count("沈三川") >= 2
    assert n >= 2


def test_repair_other_self_intro_verbs():
    # Cover the rest of the verb set: 在下/鄙人/敝人/本人.
    text = "<pc_action>在下林峰。</pc_action>"
    out, n = _repair_pc_name(text, "Riku")
    assert "林峰" not in out and "在下Riku" in out and n == 1

    text2 = "<pc_action>鄙人云野，请多关照。</pc_action>"
    out2, n2 = _repair_pc_name(text2, "Riku")
    assert "云野" not in out2 and "鄙人Riku" in out2 and n2 == 1


def test_repair_handles_empty_input():
    assert _repair_pc_name("", "Riku") == ("", 0)
    assert _repair_pc_name("<narrative>没什么发生。</narrative>", "Riku") == (
        "<narrative>没什么发生。</narrative>",
        0,
    )


def test_repair_no_op_without_character_name():
    text = "<pc_action>我叫林峰。</pc_action>"
    assert _repair_pc_name(text, "") == (text, 0)


def test_repair_mixed_say_and_pc_action():
    # PC self-intro outside <say> gets fixed; NPC self-intro inside <say>
    # is left intact in the same payload.
    text = (
        '<say speaker="林峰">「我叫林峰。」</say>'
        "<pc_action>我叫云野。</pc_action>"
    )
    out, n = _repair_pc_name(text, "Riku")
    # Inside <say>, 林峰 dialogue stays untouched.
    assert '<say speaker="林峰">「我叫林峰。」</say>' in out
    # Outside <say>, 云野 → Riku.
    assert "我叫Riku" in out
    assert "云野" not in out
    assert n == 1


def test_repair_transliterated_name_with_middle_dot():
    text = "<pc_action>我是艾米丽·斯通。</pc_action>"
    out, n = _repair_pc_name(text, "Riku")
    # 艾米丽·斯通 has 5 chars (4 hanzi + dot) — within length window 1-8.
    assert "艾米丽" not in out
    assert "Riku" in out
    assert n == 1
