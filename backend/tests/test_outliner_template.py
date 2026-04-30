from dzmm.prompts.outliner_template import build_outliner_messages


def test_outliner_messages_include_world_character_genre():
    msgs = build_outliner_messages(
        world_name="赛博朋克", world_md="霓虹之城",
        character_name="Riku", character_md="义体黑客",
        genre="悬疑探案", custom_prompt="",
    )
    assert len(msgs) >= 2  # system + user
    sys_text = msgs[0].content
    assert "TRPG 编剧" in sys_text or "outline" in sys_text.lower()
    user_text = msgs[1].content
    assert "赛博朋克" in user_text
    assert "Riku" in user_text
    assert "悬疑探案" in user_text


def test_outliner_messages_use_custom_prompt_when_provided():
    msgs = build_outliner_messages(
        world_name="奇幻", world_md="精灵森林",
        character_name="Eli", character_md="精灵射手",
        genre="自定义", custom_prompt="一场冰雪覆盖大陆的末日逃亡",
    )
    user_text = msgs[1].content
    assert "冰雪覆盖" in user_text or "末日逃亡" in user_text


def test_outliner_system_prompt_specifies_json_schema():
    msgs = build_outliner_messages(
        world_name="x", world_md="y", character_name="a", character_md="b",
        genre="悬疑探案", custom_prompt="",
    )
    sys_text = msgs[0].content
    # Must instruct model to output JSON with these fields
    assert "chapters" in sys_text
    assert "main_characters" in sys_text
    assert "ending" in sys_text
    assert "opening_hook" in sys_text


def test_outliner_constrains_chapter_count():
    """Model should be told to produce 3-5 chapters."""
    msgs = build_outliner_messages(
        world_name="x", world_md="y", character_name="a", character_md="b",
        genre="悬疑探案", custom_prompt="",
    )
    sys_text = msgs[0].content
    assert "3" in sys_text and "5" in sys_text  # chapter count guidance


def test_known_genres_constant_exposed():
    from dzmm.prompts.outliner_template import KNOWN_GENRES
    # Must include the 5 templates we promised the user
    for g in ["悬疑探案", "英雄成长", "政治阴谋", "灾难求生", "恋爱攻略"]:
        assert g in KNOWN_GENRES
