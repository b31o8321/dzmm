from dzmm.prompts.outliner_template import KNOWN_GENRES, build_outliner_messages

_REQUIRED_FIELDS = {"desc", "act_count", "ending_archetype", "required_roles"}
_KNOWN_KEYS = ["悬疑探案", "英雄成长", "政治阴谋", "灾难求生", "恋爱攻略"]


def test_each_genre_has_full_schema():
    for key in _KNOWN_KEYS:
        assert key in KNOWN_GENRES, f"Missing genre: {key}"
        spec = KNOWN_GENRES[key]
        for field in _REQUIRED_FIELDS:
            assert field in spec, f"Genre '{key}' missing field '{field}'"
        assert isinstance(spec["desc"], str) and spec["desc"]
        assert isinstance(spec["act_count"], int) and spec["act_count"] > 0
        assert isinstance(spec["ending_archetype"], str) and spec["ending_archetype"]
        assert isinstance(spec["required_roles"], list) and len(spec["required_roles"]) > 0


def test_build_outliner_messages_includes_structural_hints():
    msgs = build_outliner_messages(
        world_name="测试世界",
        world_md="一个现代都市",
        character_name="张侦探",
        character_md="老练的私家侦探",
        genre="悬疑探案",
        custom_prompt="",
    )
    user_text = msgs[1].content
    assert "类型结构" in user_text
    assert "约 3 章" in user_text
    assert "揭露真相" in user_text
    assert "怀疑对象" in user_text


def test_build_outliner_messages_structural_hints_vary_by_genre():
    """Each genre produces its own act_count and ending_archetype in the message."""
    for key in _KNOWN_KEYS:
        spec = KNOWN_GENRES[key]
        msgs = build_outliner_messages(
            world_name="W", world_md="x",
            character_name="C", character_md="y",
            genre=key,
        )
        user_text = msgs[1].content
        assert "类型结构" in user_text
        assert f"约 {spec['act_count']} 章" in user_text
        assert spec["ending_archetype"] in user_text
