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


def test_era_begin_tag_known():
    p = StreamingTagParser()
    out = collect(p, ['<era_begin name="第一章">序幕</era_begin>'])
    tag = [e for e in out if isinstance(e, TagComplete)][0]
    assert tag.name == "era_begin"
    assert tag.attrs == {"name": "第一章"}
    assert tag.content == "序幕"


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
