from dzmm.ai_world_drafts import AIWorldDraftInput, _generation_prompt
from dzmm.genre_presets import genre_preset_list, resolve_genre


def _input(genre: str) -> AIWorldDraftInput:
    return AIWorldDraftInput(
        model_profile_id="profile-1",
        ruleset="story_adventure",
        genre=genre,
        tone="克制",
        core_conflict="未解的失踪案",
        hero_preference="冷静的旁观的调查者",
    )


def test_genre_preset_list_exposes_five_canonical_genres() -> None:
    presets = genre_preset_list()
    assert [preset["id"] for preset in presets] == [
        "mystery",
        "hero_growth",
        "intrigue",
        "survival",
        "romance",
        "steampunk_western",
    ]
    for preset in presets:
        assert preset["label"] and preset["tone"] and preset["core_conflict"] and preset["guidance"]


def test_resolve_genre_expands_preset_id_and_label_but_passes_unknown_through() -> None:
    assert "悬疑探案" in resolve_genre("mystery")
    assert "搜证" in resolve_genre("悬疑探案")
    assert "对抗与斡旋" in resolve_genre("蒸汽朋克西部")
    assert resolve_genre(" mystery ") == resolve_genre("mystery")


def test_generation_prompt_brief_expands_preset_genre() -> None:
    prompt = _generation_prompt(_input("romance"))
    assert "恋爱攻略" in prompt["brief"]["genre"]
    assert prompt["brief"]["tone"] == "克制"

    custom = _generation_prompt(_input("雾都孤儿式的循环剧"))
    assert custom["brief"]["genre"] == "雾都孤儿式的循环剧"


def test_genre_presets_served_over_http(migrated_client) -> None:
    client, _ = migrated_client
    response = client.get("/api/v2/genre-presets")
    assert response.status_code == 200
    presets = response.json()
    assert len(presets) == 6 and presets[0]["id"] == "mystery"
