import base64
import json
import zlib

from test_world_compose import compose_payload


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return len(data).to_bytes(4, "big") + chunk_type + data + b"\0\0\0\0"


def _v3_png_card(*, compressed: bool = False) -> str:
    card = {
        "spec": "chara_card_v3",
        "spec_version": "3.0",
        "data": {
            "name": "岚",
            "description": "港口守卫。",
            "character_book": {"entries": []},
            "extensions": {"kept": True},
        },
    }
    encoded = base64.b64encode(json.dumps(card, ensure_ascii=False).encode())
    if compressed:
        metadata = b"chara\0\0" + zlib.compress(encoded)
        chunk_type = b"zTXt"
    else:
        metadata = b"chara\0" + encoded
        chunk_type = b"tEXt"
    png = b"\x89PNG\r\n\x1a\n" + _png_chunk(chunk_type, metadata) + _png_chunk(b"IEND", b"")
    return base64.b64encode(png).decode()


def test_sillytavern_v3_card_import_persists_a_character_card_and_round_trips(migrated_client) -> None:
    client, _ = migrated_client
    response = client.post(
        "/api/v2/content/sillytavern:import",
        json={
            "content": {
                "spec": "chara_card_v3",
                "spec_version": "3.0",
                "data": {
                    "name": "Mira",
                    "description": "A sailor.",
                    "character_book": {
                        "entries": [
                            {
                                "id": "oracle",
                                "keys": ["fog", "oracle"],
                                "content": "The harbor oracle keeps the tide ledger.",
                                "insertion_order": 70,
                                "extensions": {"vendor": "kept"},
                            }
                        ]
                    },
                },
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["suggested_hero"] == {"name": "Mira", "profile": {"description": "A sailor."}}
    assert body["lorebook"]["entries"][0]["activation"] == "keyword"
    assert body["lorebook"]["entries"][0]["keywords"] == ["fog", "oracle"]
    assert body["lorebook"]["entries"][0]["source"]["sillytavern"]["extensions"] == {"vendor": "kept"}
    card = body["character_cards"][0]
    assert card["format"] == "sillytavern_v3"
    assert card["mapped"]["description"] == "A sailor."
    assert card["mapped"]["character_book_entry_ids"] == ["card-oracle"]

    payload = compose_payload("card-world")
    payload["world_definition"]["lorebook"] = body["lorebook"]
    payload["world_definition"]["character_cards"] = body["character_cards"]
    created = client.post("/api/v2/worlds:compose", json=payload).json()
    exported = client.get(
        f"/api/v2/world-versions/{created['world_version_id']}/character-cards/{card['id']}:export"
    )
    assert exported.status_code == 200
    assert exported.json()["data"]["character_book"]["entries"][0]["extensions"] == {"vendor": "kept"}


def test_sillytavern_v3_png_card_import_preserves_the_embedded_payload(migrated_client) -> None:
    client, _ = migrated_client

    response = client.post(
        "/api/v2/content/sillytavern:import",
        json={"png_base64": _v3_png_card(compressed=True)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["report"]["source_format"] == "sillytavern_v3_png_character_card"
    assert body["report"]["supported_fields"][0] == "PNG chara metadata"
    assert body["suggested_hero"]["name"] == "岚"
    assert body["character_cards"][0]["source_payload"]["data"]["extensions"] == {"kept": True}


def test_sillytavern_non_ascii_card_names_get_stable_distinct_asset_ids(migrated_client) -> None:
    client, _ = migrated_client

    ids = []
    for name in ("岚", "沈砚"):
        response = client.post(
            "/api/v2/content/sillytavern:import",
            json={
                "content": {
                    "spec": "chara_card_v3",
                    "spec_version": "3.0",
                    "data": {"name": name, "character_book": {"entries": []}},
                }
            },
        )
        assert response.status_code == 200
        ids.append(response.json()["character_cards"][0]["id"])

    assert ids[0] != ids[1]
    assert all(card_id.startswith("card-") and card_id != "card-" for card_id in ids)


def test_sillytavern_png_import_rejects_invalid_or_ambiguous_sources(migrated_client) -> None:
    client, _ = migrated_client

    invalid = client.post("/api/v2/content/sillytavern:import", json={"png_base64": "not-base64"})
    ambiguous = client.post(
        "/api/v2/content/sillytavern:import",
        json={"content": {"entries": {}}, "png_base64": _v3_png_card()},
    )

    assert invalid.status_code == 422
    assert "valid base64" in invalid.json()["detail"]
    assert ambiguous.status_code == 422
    assert "exactly one" in str(ambiguous.json()["detail"])


def test_world_info_selection_and_explicit_lorebook_promotion_create_new_version(migrated_client) -> None:
    client, _ = migrated_client
    imported = client.post(
        "/api/v2/content/sillytavern:import",
        json={
            "content": {
                "entries": {
                    "0": {
                        "id": "weather",
                        "keys": ["rain"],
                        "content": "Rain makes the harbor stones slick.",
                        "order": 10,
                    },
                    "1": {
                        "id": "law",
                        "constant": True,
                        "content": "The harbor bell rings at midnight.",
                        "order": 5,
                    },
                }
            }
        },
    )
    assert imported.status_code == 200
    lorebook = imported.json()["lorebook"]
    assert {entry["activation"] for entry in lorebook["entries"]} == {"always", "keyword"}

    payload = compose_payload("content-world")
    payload["world_definition"]["lorebook"] = lorebook
    created = client.post("/api/v2/worlds:compose", json=payload).json()
    selected = client.post(
        f"/api/v2/world-versions/{created['world_version_id']}/lorebook:select",
        json={"player_input": "I walk through rain.", "character_budget": 100},
    )
    assert selected.status_code == 200
    assert selected.json()["included_ids"] == ["world-info-weather", "world-info-law"]
    exported = client.get(
        f"/api/v2/world-versions/{created['world_version_id']}/lorebook:export"
    )
    assert exported.status_code == 200
    assert exported.json()["entries"]["0"] == {
        "id": "weather",
        "keys": ["rain"],
        "content": "Rain makes the harbor stones slick.",
        "order": 10,
    }
    legacy_path = client.post(
        f"/api/v2/world-versions/{created['world_version_id']}/lore:select",
        json={"player_input": "I walk through rain.", "character_budget": 100},
    )
    assert legacy_path.status_code == 404

    promoted = client.post(
        f"/api/v2/worlds/{created['world_id']}/lorebook/world-info-weather:promote",
        json={"entity_kind": "npcs", "entity": {"id": "rain-warden", "name": "Rain Warden"}},
    )
    assert promoted.status_code == 200
    assert promoted.json()["version_number"] == 2
    assert promoted.json()["definition"]["npcs"] == [
        {"id": "rain-warden", "name": "Rain Warden"}
    ]

    original_run = client.get(f"/api/v2/runs/{created['run_id']}")
    assert original_run.json()["world_version_id"] == created["world_version_id"]
    assert original_run.json()["world_version_id"] != promoted.json()["id"]


def test_native_lorebook_exports_as_safe_world_info(migrated_client) -> None:
    client, _ = migrated_client
    template = client.get("/api/v2/world-templates/fog-harbor").json()
    template["request_id"] = "native-lorebook-export"
    created = client.post("/api/v2/worlds:compose", json=template).json()

    exported = client.get(
        f"/api/v2/world-versions/{created['world_version_id']}/lorebook:export"
    )

    assert exported.status_code == 200
    assert exported.json() == {
        "entries": {
            "0": {
                "id": "gray-tide",
                "comment": "灰潮",
                "content": "雾港的潮水会吞没失约者。",
                "keys": [],
                "constant": True,
                "insertion_order": 90,
            }
        }
    }


def _realistic_v3_card() -> dict:
    return {
        "spec": "chara_card_v3",
        "spec_version": "3.0",
        "data": {
            "name": "Mira",
            "description": "A sailor who reads the fog.",
            "personality": "Cautious, warm.",
            "scenario": "The harbor on the eve of the gray tide.",
            "first_mes": "You made it past the breakwater.",
            "mes_example": "<START>\n{{user}}: Who are you?\n{{char}}: A keeper of tides.",
            "alternate_greetings": ["Late again, traveler.", "The bell rang twice tonight."],
            "creator_notes": "Made for the fog-harbor campaign.",
            "creator": "dzmm-fan",
            "character_version": "1.2",
            "tags": ["mystery", "harbor"],
            "system_prompt": "Stay in character as Mira.",
            "post_history_instructions": "Keep replies under 120 words.",
            "character_book": {
                "entries": [
                    {
                        "id": "oracle",
                        "keys": ["fog", "oracle"],
                        "content": "The harbor oracle keeps the tide ledger.",
                        "insertion_order": 70,
                        "comment": "tide ledger",
                        "extensions": {"vendor": "kept"},
                    }
                ]
            },
            "extensions": {"vendor": "kept"},
        },
    }


def test_sillytavern_v3_card_import_preserves_high_frequency_fields_and_round_trips(
    migrated_client,
) -> None:
    client, _ = migrated_client
    response = client.post(
        "/api/v2/content/sillytavern:import",
        json={"content": _realistic_v3_card()},
    )

    assert response.status_code == 200
    body = response.json()
    card = body["character_cards"][0]
    mapped = card["mapped"]
    assert mapped["alternate_greetings"] == [
        "Late again, traveler.",
        "The bell rang twice tonight.",
    ]
    assert mapped["creator_notes"] == "Made for the fog-harbor campaign."
    assert mapped["creator"] == "dzmm-fan"
    assert mapped["character_version"] == "1.2"
    assert mapped["tags"] == ["mystery", "harbor"]
    assert mapped["system_prompt"] == "Stay in character as Mira."
    assert mapped["post_history_instructions"] == "Keep replies under 120 words."
    assert body["report"]["ignored_fields"] == ["extensions"]
    assert "data.alternate_greetings" in body["report"]["supported_fields"]

    payload = compose_payload("card-world-extras")
    payload["world_definition"]["lorebook"] = body["lorebook"]
    payload["world_definition"]["character_cards"] = body["character_cards"]
    created = client.post("/api/v2/worlds:compose", json=payload).json()
    exported = client.get(
        f"/api/v2/world-versions/{created['world_version_id']}/character-cards/{card['id']}:export"
    )
    assert exported.status_code == 200
    data = exported.json()["data"]
    assert data["alternate_greetings"] == _realistic_v3_card()["data"]["alternate_greetings"]
    assert data["creator_notes"] == "Made for the fog-harbor campaign."
    assert data["tags"] == ["mystery", "harbor"]
    assert data["character_book"]["entries"][0]["extensions"] == {"vendor": "kept"}


def test_native_character_card_export_backfills_high_frequency_fields(migrated_client) -> None:
    client, _ = migrated_client
    payload = compose_payload("native-card-extras")
    payload["world_definition"]["character_cards"] = [
        {
            "id": "native-hero",
            "name": "艾登",
            "format": "native",
            "mapped": {
                "description": "边境斥候。",
                "first_mes": "营地篝火旁，他抬起头。",
                "alternate_greetings": ["风雪来得比预想早。"],
                "creator_notes": "官方模板角色。",
                "creator": "dzmm",
                "character_version": "2.0",
                "tags": ["frontier"],
                "system_prompt": "以艾登的身份行动。",
                "post_history_instructions": "保持简短。",
            },
        }
    ]
    created = client.post("/api/v2/worlds:compose", json=payload).json()
    exported = client.get(
        f"/api/v2/world-versions/{created['world_version_id']}/character-cards/native-hero:export"
    )
    assert exported.status_code == 200
    data = exported.json()["data"]
    assert exported.json()["spec"] == "chara_card_v3"
    assert data["alternate_greetings"] == ["风雪来得比预想早。"]
    assert data["creator_notes"] == "官方模板角色。"
    assert data["creator"] == "dzmm"
    assert data["character_version"] == "2.0"
    assert data["tags"] == ["frontier"]
    assert data["system_prompt"] == "以艾登的身份行动。"
    assert data["post_history_instructions"] == "保持简短。"


def test_sillytavern_world_info_import_and_export_round_trips(migrated_client) -> None:
    client, _ = migrated_client
    world_info = {
        "entries": {
            "0": {
                "uid": 0,
                "key": ["gray tide"],
                "keysecondary": [],
                "comment": "灰潮",
                "content": "雾港的潮水会吞没失约者。",
                "constant": True,
                "selective": False,
                "order": 90,
                "position": 0,
                "disable": False,
                "extensions": {"timing": "before"},
            },
            "1": {
                "uid": 1,
                "key": ["lighthouse keeper"],
                "comment": "守塔人",
                "content": "守塔人三十年没有下过塔。",
                "constant": False,
                "order": 50,
                "disable": False,
            },
        }
    }
    imported = client.post(
        "/api/v2/content/sillytavern:import",
        json={"content": world_info},
    )
    assert imported.status_code == 200
    body = imported.json()
    assert body["report"]["source_format"] == "sillytavern_world_info"

    payload = compose_payload("world-info-roundtrip")
    payload["world_definition"]["lorebook"] = body["lorebook"]
    created = client.post("/api/v2/worlds:compose", json=payload).json()
    exported = client.get(
        f"/api/v2/world-versions/{created['world_version_id']}/lorebook:export"
    )
    assert exported.status_code == 200
    entries = exported.json()["entries"]
    assert entries["0"]["content"] == "雾港的潮水会吞没失约者。"
    assert entries["0"]["key"] == ["gray tide"]
    assert entries["0"]["constant"] is True
    assert entries["0"]["comment"] == "灰潮"
    assert entries["0"]["extensions"] == {"timing": "before"}
    assert entries["1"]["key"] == ["lighthouse keeper"]
    assert entries["1"]["constant"] is False
