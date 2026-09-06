from pathlib import Path

from jsonschema import validate as validate_schema

from dzmm.core.combat import apply_attack, combat_rules
from dzmm.core.command_engine import apply_commands
from dzmm.narrative import initial_state

CONTRACT = Path(__file__).parents[2] / "contracts" / "run_state.schema.json"


def _definition() -> dict:
    return {
        "name": "战斗测试世界",
        "locations": [{"id": "harbor", "name": "港口"}],
        "npcs": [
            {"id": "lan", "name": "岚", "combat": {"max_hp": 8, "ac": 13}},
            {"id": "brute", "name": "壮汉", "combat": {"max_hp": 12, "ac": 10, "attack_bonus": 4, "damage": {"count": 2, "sides": 4, "bonus": 1}}},
            {"id": "rat", "name": "巨鼠"},
        ],
        "factions": [],
        "character_cards": [],
        "events": [],
        "resources": [],
        "story": {"chapters": [], "flags": [], "relationships": [], "relationship_events": [], "routes": [], "endings": []},
        "ruleset": {"id": "trpg", "enabled_capabilities": ["trpg", "combat"]},
    }


def _state(**rule_overrides) -> dict:
    definition = _definition()
    if rule_overrides:
        definition["ruleset"]["combat_rules"] = rule_overrides
    return initial_state(definition, {"id": "hero", "name": "旅人", "profile": {}})


def _rolls(*values):
    """Script ``randbelow`` so a scripted value N becomes a natural roll of N+1."""

    sequence = iter(values)
    return lambda sides: max(0, min(next(sequence) - 1, sides - 1))


def test_default_rules_resolve_hero_and_npc_stats() -> None:
    rules = combat_rules(_state())
    assert rules["hero"] == {"max_hp": 20, "ac": 12, "attack_bonus": 3, "damage": {"count": 1, "sides": 8, "bonus": 1}}
    assert rules["npc"]["max_hp"] == 10


def test_ruleset_overrides_merge_role_by_role() -> None:
    rules = combat_rules(_state(hero={"ac": 14}, npc={"damage": {"sides": 10}}))
    assert rules["hero"]["ac"] == 14
    assert rules["hero"]["attack_bonus"] == 3
    assert rules["npc"]["damage"] == {"count": 1, "sides": 10, "bonus": 0}
    assert rules["npc"]["ac"] == 11


def test_hit_applies_damage_and_persists_participants(monkeypatch) -> None:
    from dzmm.core import combat

    state = _state()
    monkeypatch.setattr(combat, "randbelow", _rolls(14, 4))  # attack roll, damage roll

    outcome = apply_attack(state, _definition(), {"target_id": "lan"})

    assert outcome == {
        "type": "attack",
        "attacker_id": "hero",
        "target_id": "lan",
        "roll": 14,
        "hit": True,
        "damage": 5,  # 1d8(4) + 1 bonus
        "target_hp": 3,
        "defeated": False,
    }
    lan = state["combat"]["participants"]["lan"]
    assert lan["hp"] == 3 and lan["max_hp"] == 8 and lan["ac"] == 13
    hero = state["combat"]["participants"]["hero"]
    assert hero["hp"] == hero["max_hp"] == 20


def test_fumble_always_misses_and_crit_doubles_damage(monkeypatch) -> None:
    from dzmm.core import combat

    state = _state()
    monkeypatch.setattr(combat, "randbelow", _rolls(1, 6, 6))
    outcome = apply_attack(state, _definition(), {"target_id": "lan"})
    assert outcome["hit"] is False and outcome["damage"] == 0

    state = _state()
    monkeypatch.setattr(combat, "randbelow", _rolls(20, 5, 4))
    outcome = apply_attack(state, _definition(), {"target_id": "lan"})
    assert outcome["hit"] is True and outcome["damage"] == 10  # crit: 1d8(5)+1 + 1d8(4)+1
    assert outcome["target_hp"] == 0 and outcome["defeated"] is True


def test_defeated_target_rejects_further_attacks(monkeypatch) -> None:
    from dzmm.core import combat
    from dzmm.narrative import NarrativeRuleError

    state = _state()
    monkeypatch.setattr(combat, "randbelow", _rolls(20, 6, 6))
    apply_attack(state, _definition(), {"target_id": "lan"})
    try:
        apply_attack(state, _definition(), {"target_id": "lan"})
        raise AssertionError("expected NarrativeRuleError")
    except NarrativeRuleError as error:
        assert "already defeated" in str(error)


def test_ruleset_override_changes_hit_threshold(monkeypatch) -> None:
    from dzmm.core import combat

    definition = _definition()
    definition["ruleset"]["combat_rules"] = {"npc": {"ac": 25}}
    state = initial_state(definition, {"id": "hero", "name": "旅人", "profile": {}})
    monkeypatch.setattr(combat, "randbelow", _rolls(19))
    outcome = apply_attack(state, definition, {"target_id": "rat"})
    assert outcome["hit"] is False  # 19 + 3 would hit role-default AC, but ruleset raised it to 25


def test_npc_can_attack_hero_with_definition_stats(monkeypatch) -> None:
    from dzmm.core import combat

    state = _state()
    # brute: +4 bonus, 2d4+1 damage; hero AC 12
    monkeypatch.setattr(combat, "randbelow", _rolls(9, 3, 2))
    outcome = apply_attack(state, _definition(), {"attacker_id": "brute", "target_id": "hero"})
    assert outcome["hit"] is True  # 9 + 4 = 13 >= 12
    assert outcome["damage"] == 6 and outcome["target_hp"] == 14


def test_unknown_participant_and_self_target_are_rejected() -> None:
    from dzmm.narrative import NarrativeRuleError

    state = _state()
    for payload in ({"target_id": "ghost"}, {"attacker_id": "hero", "target_id": "hero"}):
        try:
            apply_attack(state, _definition(), payload)
            raise AssertionError("expected NarrativeRuleError")
        except NarrativeRuleError:
            pass


def test_command_engine_gates_attack_behind_combat_capability() -> None:
    class FakeError(Exception):
        pass

    definition = _definition()
    definition["ruleset"] = {"id": "trpg", "enabled_capabilities": ["trpg"]}
    state = initial_state(definition, {"id": "hero", "name": "旅人", "profile": {}})
    try:
        apply_commands(
            state,
            definition,
            [{"type": "attack", "payload": {"target_id": "lan"}}],
            validate_command=lambda command: None,
            error_type=FakeError,
        )
        raise AssertionError("expected gating error")
    except FakeError as error:
        assert "combat" in str(error)


def test_command_engine_applies_attack_and_audits_outcome(monkeypatch) -> None:
    from dzmm.core import combat

    definition = _definition()
    state = initial_state(definition, {"id": "hero", "name": "旅人", "profile": {}})
    monkeypatch.setattr(combat, "randbelow", _rolls(12, 3))
    outcomes = apply_commands(
        state,
        definition,
        [{"type": "attack", "payload": {"target_id": "lan"}}],
        validate_command=lambda command: None,
        error_type=ValueError,
    )
    assert outcomes[0]["type"] == "attack" and outcomes[0]["hit"] is True


def test_initial_state_and_combat_state_match_run_state_contract() -> None:
    import json

    schema = json.loads(CONTRACT.read_text())
    state = _state()
    apply_attack(state, _definition(), {"target_id": "lan"})
    validate_schema(state, schema)
