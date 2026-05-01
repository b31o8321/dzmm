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


# v0.1.8: real LM Studio output observed in the wild — model uses `#` as a
# placeholder for the PC name. Repair must replace it before persistence so
# the next turn's prompt doesn't compound the drift.


def test_repair_replaces_hash_placeholder_before_cjk():
    text = '<pc_action>#站起身去帮修女遮雨，掌心仍在出汗。</pc_action>'
    out, n = _repair_pc_name(text, 'Riku')
    assert '#' not in out
    assert 'Riku站起身' in out
    assert n == 1


def test_repair_replaces_hash_placeholder_in_narrative():
    """Real session: 'narrative 中提到「记下了#的特征」' — # = PC name."""
    text = '<narrative>修道院管理人员记下了#的特征，并攻击#。</narrative>'
    out, n = _repair_pc_name(text, '沈三川')
    assert '#' not in out
    assert '记下了沈三川的特征' in out
    assert '攻击沈三川' in out
    assert n == 2


def test_repair_does_not_touch_markdown_heading():
    """`## 基本信息` is a markdown heading, NOT a name slot."""
    text = '## 基本信息\n性别：男'
    out, n = _repair_pc_name(text, 'Riku')
    assert out == text
    assert n == 0


def test_repair_does_not_touch_hash_inside_say_block():
    """A NPC literally saying '#' (rare, but possible) should be left alone
    so we don't trample NPC dialogue."""
    text = '<say speaker="管理人员">「#是什么意思？」</say>'
    out, n = _repair_pc_name(text, 'Riku')
    assert '#' in out  # NPC dialogue preserved
    assert 'Riku' not in out
