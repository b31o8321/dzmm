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
