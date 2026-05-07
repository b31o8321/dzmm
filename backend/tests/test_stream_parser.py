from dzmm.parsing.events import NarrativeDelta, TagComplete, ParseError
from dzmm.parsing.stream_parser import StreamingTagParser


def collect(parser: StreamingTagParser, chunks: list[str]) -> list:
    out = []
    for c in chunks:
        out.extend(parser.feed(c))
    out.extend(parser.finish())
    return out


def test_streams_narrative_text_live():
    p = StreamingTagParser()
    out = collect(p, ["<narrative>Hello", " world</narrative>"])
    deltas = [e.text for e in out if isinstance(e, NarrativeDelta)]
    assert "".join(deltas) == "Hello world"


def test_buffers_state_change_until_close():
    p = StreamingTagParser()
    out = collect(p, ['<state_change>{"hp":-5}</state_change>'])
    tags = [e for e in out if isinstance(e, TagComplete)]
    assert len(tags) == 1
    assert tags[0].name == "state_change"
    assert tags[0].content == '{"hp":-5}'


def test_handles_split_open_tag():
    p = StreamingTagParser()
    out = collect(p, ["<narr", "ative>hi</narrative>"])
    deltas = [e.text for e in out if isinstance(e, NarrativeDelta)]
    assert "".join(deltas) == "hi"


def test_handles_split_close_tag():
    p = StreamingTagParser()
    out = collect(p, ["<narrative>hi</narra", "tive>"])
    deltas = [e.text for e in out if isinstance(e, NarrativeDelta)]
    assert "".join(deltas) == "hi"


def test_extracts_tag_attributes():
    p = StreamingTagParser()
    out = collect(p, ['<dice skill="潜行" target="15">d20=8</dice>'])
    tag = [e for e in out if isinstance(e, TagComplete)][0]
    assert tag.name == "dice"
    assert tag.attrs == {"skill": "潜行", "target": "15"}
    assert tag.content == "d20=8"


def test_drops_unknown_tags_silently():
    p = StreamingTagParser()
    out = collect(p, ["<weird>junk</weird><narrative>real</narrative>"])
    deltas = [e.text for e in out if isinstance(e, NarrativeDelta)]
    tags = [e for e in out if isinstance(e, TagComplete)]
    errors = [e for e in out if isinstance(e, ParseError)]
    assert "".join(deltas) == "real"
    assert len(tags) == 0
    assert len(errors) == 0


# ── v0.9: dice 扩展为带 <scene> + <reaction> 的演出标签 ──────
# 解析器对 dice 的 body 不做嵌套解析——它把 <dice> 和 </dice>
# 之间的所有文本（包括 <scene>...</scene><reaction>...</reaction>）
# 整体存进 content；前端 DiceShowcase 自己 split。

def test_dice_with_nested_scene_and_reaction():
    p = StreamingTagParser()
    body = (
        '<scene>李少卿屏住呼吸，靠在阴影里。</scene>'
        '<reaction speaker="守卫张三" mood="无察觉">「这风也太冷了……」</reaction>'
    )
    chunk = f'<dice category="stealth" outcome="success" dc="12" pc_roll="15" mod="+2">{body}</dice>'
    out = collect(p, [chunk])
    tags = [e for e in out if isinstance(e, TagComplete)]
    assert len(tags) == 1
    assert tags[0].name == "dice"
    assert tags[0].attrs["category"] == "stealth"
    assert tags[0].attrs["outcome"] == "success"
    # The content is preserved verbatim — DiceShowcase parses scene/reaction front-end.
    assert "<scene>" in tags[0].content
    assert "李少卿屏住呼吸" in tags[0].content
    assert '<reaction speaker="守卫张三"' in tags[0].content
    assert "这风" in tags[0].content


def test_dice_legacy_plain_text_still_works():
    """老格式 <dice>plain text</dice> 在 v0.9 之后仍然合法（向后兼容）。"""
    p = StreamingTagParser()
    out = collect(p, ['<dice category="combat" outcome="success" dc="14" pc_roll="17">攻击命中骷髅卫兵</dice>'])
    tags = [e for e in out if isinstance(e, TagComplete)]
    assert len(tags) == 1
    assert tags[0].content == "攻击命中骷髅卫兵"


def test_v09_combat_and_faction_tags_recognized():
    """v0.9 新增的 combat_start/combat_end/faction_create/faction_change 已加入 KNOWN_TAGS。

    Attribute regex only accepts double-quoted values, so JSON in
    `enemies` must be passed as content (or the attribute uses
    pre-escaped form). For this test we keep the enemies list in content.
    """
    p = StreamingTagParser()
    out = collect(p, [
        '<combat_start>[{"name": "骷髅"}]</combat_start>',
        '<faction_create name="暗影教团" ideology="颠覆王权">古老的秘密结社</faction_create>',
        '<faction_change name="暗影教团" rep_delta="-10"/>',
        '<combat_end winner="pc"/>',
    ])
    tags = [e for e in out if isinstance(e, TagComplete)]
    names = [t.name for t in tags]
    assert names == ["combat_start", "faction_create", "faction_change", "combat_end"]
    assert "骷髅" in tags[0].content


def test_drops_outside_text():
    p = StreamingTagParser()
    out = collect(p, ["preamble <narrative>real</narrative> trailing"])
    deltas = [e.text for e in out if isinstance(e, NarrativeDelta)]
    assert "".join(deltas) == "real"


def test_emits_multiple_tags_in_order():
    p = StreamingTagParser()
    out = collect(p, [
        "<narrative>You sneak past.</narrative>",
        "<dice skill=\"潜行\" target=\"12\">d20=14, 成功</dice>",
        '<state_change>{"sanity":-1}</state_change>',
    ])
    names = [e.name if isinstance(e, TagComplete) else "narrative"
             for e in out
             if isinstance(e, (TagComplete, NarrativeDelta))]
    assert "dice" in names
    assert "state_change" in names
    assert names.index("dice") < names.index("state_change")


def test_unclosed_buffered_tag_emits_error():
    p = StreamingTagParser()
    out = collect(p, ['<state_change>{"hp":-5'])
    errors = [e for e in out if isinstance(e, ParseError)]
    assert len(errors) == 1
    assert "state_change" in errors[0].message


def test_finish_unclosed_buffered_tag_emits_partial_tag_complete():
    """v0.1.9: when stream ends mid-tag (e.g. token cap hit inside <choices>),
    finish() now also emits a synthetic TagComplete with the partial buffer
    so callers can apply what they got instead of dropping it entirely.
    Fixes 'Unclosed tag <choices>' real-play feedback."""
    p = StreamingTagParser()
    list(p.feed("<choices>\n- A\n- B"))  # never closed
    events = list(p.finish())

    errors = [e for e in events if isinstance(e, ParseError)]
    assert any("choices" in e.message for e in errors), (
        "ParseError warning still emitted on unclosed buffered tag"
    )
    completes = [e for e in events if isinstance(e, TagComplete)]
    assert len(completes) == 1, "synthetic TagComplete now emitted"
    assert completes[0].name == "choices"
    assert "A" in completes[0].content and "B" in completes[0].content


def test_unclosed_narrative_flushes_on_finish():
    p = StreamingTagParser()
    p.feed("<narrative>partial output")
    out = list(p.finish())
    deltas = [e.text for e in out if isinstance(e, NarrativeDelta)]
    assert "partial output" in "".join(deltas)


def test_fine_grained_chunking_per_character():
    full = '<narrative>Hi.</narrative><state_change>{"hp":-1}</state_change>'
    p = StreamingTagParser()
    events = []
    for ch in full:
        events.extend(p.feed(ch))
    events.extend(p.finish())

    deltas = [e.text for e in events if isinstance(e, NarrativeDelta)]
    tags = [e for e in events if isinstance(e, TagComplete)]
    assert "".join(deltas) == "Hi."
    assert len(tags) == 1
    assert tags[0].name == "state_change"
    assert tags[0].content == '{"hp":-1}'


def test_character_xp_tag_known():
    p = StreamingTagParser()
    out = collect(p, ['<character_xp delta="50">完成任务</character_xp>'])
    tag = [e for e in out if isinstance(e, TagComplete)][0]
    assert tag.name == "character_xp"
    assert tag.attrs == {"delta": "50"}
    assert tag.content == "完成任务"


def test_attrs_with_spaces_and_quotes():
    p = StreamingTagParser()
    out = collect(p, [
        '<plot_event type="new_quest" importance="3">引子任务</plot_event>'
    ])
    tag = [e for e in out if isinstance(e, TagComplete)][0]
    assert tag.attrs == {"type": "new_quest", "importance": "3"}


def test_recall_tag_in_known():
    """Self-closing <recall name="X"/> emits a TagComplete with the name attr."""
    p = StreamingTagParser()
    out = collect(p, ['<recall name="御坂雪" />'])
    tags = [e for e in out if isinstance(e, TagComplete)]
    assert len(tags) == 1
    assert tags[0].name == "recall"
    assert tags[0].attrs == {"name": "御坂雪"}
    assert tags[0].content == ""


def test_pc_goal_tag_known():
    p = StreamingTagParser()
    out = collect(p, [
        '<pc_goal type="add" priority="high">找到黑医</pc_goal>'
    ])
    tag = [e for e in out if isinstance(e, TagComplete)][0]
    assert tag.name == "pc_goal"
    assert tag.attrs == {"type": "add", "priority": "high"}
    assert tag.content == "找到黑医"


def test_recall_tag_no_space_self_close():
    """`<recall name="X"/>` without trailing space is also accepted."""
    p = StreamingTagParser()
    out = collect(p, ['<narrative>hello</narrative><recall name="A"/>'])
    tags = [e for e in out if isinstance(e, TagComplete)]
    assert any(t.name == "recall" and t.attrs.get("name") == "A" for t in tags)


def test_pc_mood_tag_known():
    p = StreamingTagParser()
    out = collect(p, ['<pc_mood>{"tense":+20,"exhausted":+10}</pc_mood>'])
    tag = [e for e in out if isinstance(e, TagComplete)][0]
    assert tag.name == "pc_mood"
    assert "tense" in tag.content
    assert "exhausted" in tag.content


def test_npc_relation_tag_known():
    p = StreamingTagParser()
    out = collect(p, [
        '<npc_relation between="御坂雪,卫兵长" kind="父女">'
        '失散多年的女儿。'
        '</npc_relation>'
    ])
    tag = [e for e in out if isinstance(e, TagComplete)][0]
    assert tag.name == "npc_relation"
    assert tag.attrs == {"between": "御坂雪,卫兵长", "kind": "父女"}
    assert "失散多年" in tag.content


# ---------------------------------------------------------------------------
# v0.10 task A: typo-tolerant close tags + new known tags
# ---------------------------------------------------------------------------


def test_typo_close_tag_narriative_recovers():
    """`</narriative>` (extra `i`) should close the open <narrative> and let
    the following <npc_update> parse normally, with a ParseError warning."""
    p = StreamingTagParser()
    events = list(p.feed(
        "<narrative>大家好</narriative><npc_update>{}</npc_update>"
    ))
    events.extend(p.finish())

    tag_completes = [e for e in events if isinstance(e, TagComplete)]
    assert any(t.name == "npc_update" for t in tag_completes)

    parse_errors = [e for e in events if isinstance(e, ParseError)]
    assert any("typo" in pe.message.lower() for pe in parse_errors)

    deltas = [e.text for e in events if isinstance(e, NarrativeDelta)]
    assert "大家好" in "".join(deltas)


def test_typo_close_tag_state_chnage_recovers():
    """A buffered tag with a typo close should still emit TagComplete."""
    p = StreamingTagParser()
    events = list(p.feed('<state_change>{"hp":-1}</state_chnage>'))
    events.extend(p.finish())

    tags = [e for e in events if isinstance(e, TagComplete)]
    assert len(tags) == 1
    assert tags[0].name == "state_change"
    assert tags[0].content == '{"hp":-1}'

    errors = [e for e in events if isinstance(e, ParseError)]
    assert any("typo" in e.message.lower() for e in errors)


def test_far_off_close_tag_still_dropped():
    """`</foobar>` is too dissimilar from `narrative` to be treated as a
    typo close — narrative stays open and never emits TagComplete."""
    p = StreamingTagParser()
    events = list(p.feed("<narrative>x</foobar>"))
    # Don't call finish(); we just want to confirm no narrative TagComplete
    # has been produced from the bogus close tag.
    completes = [e for e in events if isinstance(e, TagComplete)]
    assert not any(t.name == "narrative" for t in completes)


def test_say_tag_with_speaker():
    p = StreamingTagParser()
    out = collect(p, ['<say speaker="小菱">「你救了我。」</say>'])
    sa = [e for e in out if isinstance(e, TagComplete) and e.name == "say"]
    assert len(sa) == 1
    assert sa[0].attrs.get("speaker") == "小菱"
    assert "你救了我" in sa[0].content


def test_hidden_event_tag_self_closing():
    p = StreamingTagParser()
    raw = (
        '<hidden_event subject="小菱" kind="injury" severity="2" '
        'description="渗血" consequence="5回合不治会昏迷"/>'
    )
    out = collect(p, [raw])
    he = [e for e in out if isinstance(e, TagComplete) and e.name == "hidden_event"]
    assert len(he) == 1
    assert he[0].attrs.get("subject") == "小菱"
    assert he[0].attrs.get("kind") == "injury"
    assert he[0].attrs.get("severity") == "2"


def test_hidden_event_tag_with_content():
    p = StreamingTagParser()
    raw = '<hidden_event subject="X" kind="secret">隐藏说明</hidden_event>'
    out = collect(p, [raw])
    he = [e for e in out if isinstance(e, TagComplete) and e.name == "hidden_event"]
    assert len(he) == 1
    assert he[0].content == "隐藏说明"


def test_pc_action_tag():
    p = StreamingTagParser()
    out = collect(p, ["<pc_action>沈三川转身离开</pc_action>"])
    pa = [e for e in out if isinstance(e, TagComplete) and e.name == "pc_action"]
    assert len(pa) == 1
    assert "沈三川" in pa[0].content


def test_scene_shift_tag():
    p = StreamingTagParser()
    out = collect(p, ['<scene_shift to="后院">天色已晚</scene_shift>'])
    ss = [e for e in out if isinstance(e, TagComplete) and e.name == "scene_shift"]
    assert len(ss) == 1
    assert ss[0].attrs == {"to": "后院"}
    assert ss[0].content == "天色已晚"


# ---------------------------------------------------------------------------
# v0.1.0 task B: screenplay-driven tags (chapter_advance / event_complete /
# plot_turn / ending). Self-closing variants for chapter_advance + ending,
# attribute-bearing for event_complete + plot_turn.
# ---------------------------------------------------------------------------


def test_chapter_advance_tag_known():
    """Self-closing <chapter_advance/> emits a TagComplete with empty content."""
    p = StreamingTagParser()
    out = collect(p, ["<chapter_advance/>"])
    tags = [e for e in out if isinstance(e, TagComplete)]
    assert len(tags) == 1
    assert tags[0].name == "chapter_advance"
    assert tags[0].attrs == {}
    assert tags[0].content == ""


def test_event_complete_tag_with_attrs():
    """<event_complete chapter=N event=M type=main|optional/> carries indices."""
    p = StreamingTagParser()
    out = collect(p, ['<event_complete chapter="1" event="0" type="main"/>'])
    tags = [e for e in out if isinstance(e, TagComplete) and e.name == "event_complete"]
    assert len(tags) == 1
    assert tags[0].attrs == {"chapter": "1", "event": "0", "type": "main"}
    assert tags[0].content == ""


def test_plot_turn_tag_with_impact():
    """<plot_turn impact=major|minor description=...> records PC pivotal moments."""
    p = StreamingTagParser()
    out = collect(p, [
        '<plot_turn impact="major" description="PC 杀了线人陈子轩"></plot_turn>'
    ])
    tags = [e for e in out if isinstance(e, TagComplete) and e.name == "plot_turn"]
    assert len(tags) == 1
    assert tags[0].attrs.get("impact") == "major"
    assert "陈子轩" in tags[0].attrs.get("description", "")


def test_ending_tag_known():
    """Self-closing <ending/> signals story conclusion."""
    p = StreamingTagParser()
    out = collect(p, ["<ending/>"])
    tags = [e for e in out if isinstance(e, TagComplete)]
    assert len(tags) == 1
    assert tags[0].name == "ending"
    assert tags[0].content == ""
