from test_world_compose import compose_payload


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
