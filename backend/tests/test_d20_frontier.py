import json
from pathlib import Path

from jsonschema import validate as validate_schema

from dzmm.core.combat import apply_attack
from dzmm.narrative import initial_state, validate_definition
from dzmm.world_templates import d20_frontier_template

CONTRACT = Path(__file__).parents[2] / "contracts" / "run_state.schema.json"


def test_d20_frontier_definition_is_valid_and_combat_enabled() -> None:
    template = d20_frontier_template()
    definition = template["world_definition"]
    validate_definition(definition)

    assert "combat" in definition["ruleset"]["enabled_capabilities"]
    assert definition["ruleset"]["combat_rules"]["hero"]["max_hp"] == 22
    assert template["hero"]["combat"] == {"max_hp": 22}


def test_d20_frontier_state_matches_contract_and_resolves_attacks() -> None:
    template = d20_frontier_template()
    definition = template["world_definition"]
    state = initial_state(definition, template["hero"])
    validate_schema(state, json.loads(CONTRACT.read_text()))

    hero = state["combat"]["participants"]  # empty until first attack
    assert hero == {}

    outcome = apply_attack(state, definition, {"target_id": "goblin-chief"})
    assert outcome["type"] == "attack" and outcome["target_hp"] >= 0
    # ruleset overrides merged: hero max_hp 22 from combat_rules, goblin ac 12
    assert state["combat"]["participants"]["hero"]["max_hp"] == 22
    assert state["combat"]["participants"]["goblin-chief"]["ac"] == 12


def test_d20_frontier_template_served_and_composes_over_http(migrated_client) -> None:
    client, _ = migrated_client

    served = client.get("/api/v2/world-templates/d20-frontier")
    assert served.status_code == 200
    template = served.json()
    assert template["world_definition"]["ruleset"]["combat_rules"]["hero"]["ac"] == 13

    composed = client.post(
        "/api/v2/worlds:compose",
        json={
            "request_id": "d20-compose-1",
            "world_definition": template["world_definition"],
            "hero": template["hero"],
        },
    )
    assert composed.status_code == 201, composed.json()
    composed_state = composed.json()["state"]
    assert composed_state["ruleset"]["enabled_capabilities"] == [
        "trpg",
        "combat",
        "chapters",
        "choices",
        "endings",
        "resources",
    ]
    assert composed_state["hero"]["combat"] == {"max_hp": 22}
