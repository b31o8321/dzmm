from test_world_compose import compose_payload


def test_sillytavern_v3_card_import_preserves_raw_lore_fields(migrated_client) -> None:
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
    assert body["lore"][0]["activation"] == "keyword"
    assert body["lore"][0]["keywords"] == ["fog", "oracle"]
    assert body["lore"][0]["source"]["sillytavern"]["extensions"] == {"vendor": "kept"}


def test_world_info_selection_and_explicit_lore_promotion_create_new_version(migrated_client) -> None:
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
    lore = imported.json()["lore"]
    assert {entry["activation"] for entry in lore} == {"always", "keyword"}

    payload = compose_payload("content-world")
    payload["world_definition"]["lore"] = lore
    created = client.post("/api/v2/worlds:compose", json=payload).json()
    selected = client.post(
        f"/api/v2/world-versions/{created['world_version_id']}/lore:select",
        json={"player_input": "I walk through rain.", "character_budget": 100},
    )
    assert selected.status_code == 200
    assert selected.json()["included_ids"] == ["world-info-weather", "world-info-law"]

    promoted = client.post(
        f"/api/v2/worlds/{created['world_id']}/lore/world-info-weather:promote",
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
