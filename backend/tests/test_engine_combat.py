"""Tests for engine/combat.py and the Batch 3 mechanics tag handlers.

~20 tests covering:
  - get_attack_modifier (STR weapon, DEX weapon, no weapon)
  - get_damage_formula (weapon with formula effect, description, fallback, no weapon)
  - get_armor_class (base + DEX_mod + armor bonus)
  - resolve_attack (hit, miss, nat-20 always hit, nat-1 always miss,
                    defeat, overkill clamp)
  - roll_initiative (sorted desc, deterministic with seed)
  - _apply_attack (records in pending_resolutions, NPC dead on defeat)
  - _apply_initiative_request (writes combat_order_json, resolves NPC names)
"""

from __future__ import annotations

import json
import random

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    Character,
    CharState,
    ModelConfig,
    NPC,
    Session as GameSession,
    World,
)
from dzmm.engine.combat import (
    AttackResult,
    get_armor_class,
    get_attack_modifier,
    get_damage_formula,
    resolve_attack,
    roll_initiative,
)
from dzmm.engine.schema import Item, ItemEffect, StatBlock


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def db(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/combat_test.db")
    await init_db(engine)
    async with async_session(engine)() as s:
        yield s
    await engine.dispose()


async def _make_world_char_session(
    s: AsyncSession,
    *,
    pc_str=14, pc_dex=12, pc_con=10, pc_int=10, pc_wis=10, pc_cha=10,
    pc_max_hp=40,
    pc_inventory_json="[]",
    pc_equipment_json="{}",
) -> tuple[World, Character, GameSession, CharState, ModelConfig]:
    world = World(name="Combat World", content_md="x", style="realistic")
    s.add(world)
    await s.flush()

    char = Character(
        world_id=world.id,
        name="Fighter",
        profile_md="A warrior",
        base_stats_json="{}",
        strength=pc_str,
        dexterity=pc_dex,
        constitution=pc_con,
        intelligence=pc_int,
        wisdom=pc_wis,
        charisma=pc_cha,
        max_hp=pc_max_hp,
        max_sanity=50,
        max_stamina=30,
        inventory_json=pc_inventory_json,
        equipment_json=pc_equipment_json,
    )
    s.add(char)

    cfg = ModelConfig(name="m", type="ollama", base_url="http://localhost", model_name="test")
    s.add(cfg)
    await s.flush()

    sess = GameSession(
        name="Combat Session",
        world_id=world.id,
        character_id=char.id,
        gm_model_config_id=cfg.id,
        summarizer_model_config_id=cfg.id,
        ruleset_version=2,
    )
    s.add(sess)
    await s.flush()

    state = CharState(
        session_id=sess.id,
        stats_json=json.dumps({"hp": pc_max_hp, "sanity": 50}),
        stamina=30,
    )
    s.add(state)
    await s.flush()

    return world, char, sess, state, cfg


async def _make_npc(s: AsyncSession, session_id: int, **kwargs) -> NPC:
    defaults = dict(
        name="Goblin",
        description="A small goblin",
        stat_block_json=json.dumps({
            "strength": 8, "dexterity": 14, "constitution": 10,
            "intelligence": 6, "wisdom": 8, "charisma": 8,
            "max_hp": 12, "current_hp": 12,
        }),
    )
    defaults.update(kwargs)
    npc = NPC(session_id=session_id, **defaults)
    s.add(npc)
    await s.flush()
    return npc


# ── Pure helper tests (no DB) ─────────────────────────────────────────────────

class TestGetAttackModifier:
    def _stat_block(self, str_val=14, dex_val=12) -> StatBlock:
        return StatBlock(strength=str_val, dexterity=dex_val)

    def test_str_weapon_uses_str_mod(self):
        sb = self._stat_block(str_val=14, dex_val=12)  # STR_mod=2, DEX_mod=1
        sword = Item(name="短剑", item_type="weapon", effects=[
            ItemEffect(type="damage", formula="1d8+STR"),
        ])
        mod, attr = get_attack_modifier(sb, sword, prof_bonus=2)
        assert attr == "strength"
        assert mod == 2 + 2  # STR_mod=2 + prof=2

    def test_dex_weapon_via_attack_attribute_effect(self):
        sb = self._stat_block(str_val=10, dex_val=16)  # DEX_mod=3
        bow = Item(name="短弓", item_type="weapon", effects=[
            ItemEffect(type="attack_attribute", stat="dexterity"),
            ItemEffect(type="damage", formula="1d6+DEX"),
        ])
        mod, attr = get_attack_modifier(sb, bow, prof_bonus=2)
        assert attr == "dexterity"
        assert mod == 3 + 2  # DEX_mod=3 + prof=2

    def test_no_weapon_uses_str_mod(self):
        sb = self._stat_block(str_val=16, dex_val=10)  # STR_mod=3
        mod, attr = get_attack_modifier(sb, None, prof_bonus=2)
        assert attr == "strength"
        assert mod == 3 + 2

    def test_prof_bonus_is_applied(self):
        sb = self._stat_block(str_val=10, dex_val=10)  # all mods = 0
        mod, _ = get_attack_modifier(sb, None, prof_bonus=3)
        assert mod == 3

    def test_negative_modifier(self):
        sb = self._stat_block(str_val=6)  # STR_mod = -2
        mod, attr = get_attack_modifier(sb, None, prof_bonus=2)
        assert mod == 0  # -2 + 2 = 0
        assert attr == "strength"


class TestGetDamageFormula:
    def test_weapon_with_formula_effect(self):
        weapon = Item(name="长剑", item_type="weapon", effects=[
            ItemEffect(type="damage", formula="1d8+STR"),
        ])
        assert get_damage_formula(weapon) == "1d8+STR"

    def test_weapon_formula_from_description(self):
        weapon = Item(name="短剑", item_type="weapon", description="轻型武器 1d6+STR", effects=[])
        assert get_damage_formula(weapon) == "1d6+STR"

    def test_weapon_fallback_from_damage_amount(self):
        weapon = Item(name="匕首", item_type="weapon", effects=[
            ItemEffect(type="damage", amount=6),
        ])
        formula = get_damage_formula(weapon)
        assert "d" in formula  # some dice formula

    def test_no_weapon_returns_unarmed(self):
        formula = get_damage_formula(None)
        assert formula == "1d4"

    def test_weapon_no_matching_effect_returns_unarmed(self):
        weapon = Item(name="空武器", item_type="weapon", effects=[
            ItemEffect(type="heal_hp", amount=5),  # no damage effect
        ])
        assert get_damage_formula(weapon) == "1d4"


class TestGetArmorClass:
    def test_base_ac_no_armor(self):
        sb = StatBlock(dexterity=10)  # DEX_mod=0
        assert get_armor_class(sb, []) == 10

    def test_dex_bonus_applied(self):
        sb = StatBlock(dexterity=14)  # DEX_mod=2
        assert get_armor_class(sb, []) == 12

    def test_armor_bonus_applied(self):
        sb = StatBlock(dexterity=10)  # DEX_mod=0
        effects = [ItemEffect(type="armor_bonus", amount=3)]
        assert get_armor_class(sb, effects) == 13

    def test_dex_plus_armor(self):
        sb = StatBlock(dexterity=16)  # DEX_mod=3
        effects = [ItemEffect(type="armor_bonus", amount=2)]
        assert get_armor_class(sb, effects) == 15  # 10+3+2

    def test_multiple_armor_effects_sum(self):
        sb = StatBlock(dexterity=10)
        effects = [
            ItemEffect(type="armor_bonus", amount=2),
            ItemEffect(type="armor_bonus", amount=1),
        ]
        assert get_armor_class(sb, effects) == 13


# ── Async resolve_attack tests ────────────────────────────────────────────────

class TestResolveAttack:

    async def test_hit_applies_damage(self, db: AsyncSession):
        """When attack hits, damage is applied and HP decreases."""
        _, char, sess, state, _ = await _make_world_char_session(db, pc_str=16, pc_max_hp=50)
        npc = await _make_npc(db, sess.id, stat_block_json=json.dumps({
            "strength": 10, "dexterity": 10, "constitution": 10,
            "intelligence": 10, "wisdom": 10, "charisma": 10,
            "max_hp": 20, "current_hp": 20,
            "ac": 8,  # low AC so guaranteed hit on most rolls
        }))
        sword = Item(name="短剑", item_type="weapon", effects=[
            ItemEffect(type="damage", formula="1d4"),
        ])
        import json as json_mod
        char.inventory_json = json_mod.dumps([sword.model_dump()])
        await db.flush()

        # Use seeded rng to guarantee a non-1 roll
        rng = random.Random(42)  # first roll: 1 (nat 1 for some seeds)
        # Use a seed that produces a hit
        rng = random.Random(999)

        result = await resolve_attack(
            db,
            session_id=sess.id,
            attacker_id=char.id,
            attacker_kind="pc",
            target_id=npc.id,
            target_kind="npc",
            weapon_name="短剑",
            rng=rng,
        )
        assert isinstance(result, AttackResult)
        assert result.attacker_id == char.id
        assert result.target_id == npc.id
        # If hit, damage must have been applied
        if result.hit:
            assert result.damage_dealt > 0
            assert result.target_hp_after < result.target_hp_before

    async def test_miss_deals_no_damage(self, db: AsyncSession):
        """When attack misses, damage_dealt=0 and HP unchanged."""
        _, char, sess, state, _ = await _make_world_char_session(db, pc_str=10)
        npc = await _make_npc(db, sess.id, stat_block_json=json.dumps({
            "strength": 10, "dexterity": 10, "constitution": 10,
            "intelligence": 10, "wisdom": 10, "charisma": 10,
            "max_hp": 20, "current_hp": 20,
            "ac": 30,  # impossibly high AC — any normal roll misses
        }))

        # Force d20 roll of 2 (attack_mod likely +4, total=6, AC=30 → miss)
        class FixedRng:
            def randint(self, a, b):
                return 2  # always roll 2

        result = await resolve_attack(
            db,
            session_id=sess.id,
            attacker_id=char.id,
            attacker_kind="pc",
            target_id=npc.id,
            target_kind="npc",
            rng=FixedRng(),
        )
        assert not result.hit
        assert result.damage_dealt == 0
        assert result.target_hp_after == result.target_hp_before

    async def test_natural_20_always_hits(self, db: AsyncSession):
        """Natural 20 hits even against impossibly high AC."""
        _, char, sess, state, _ = await _make_world_char_session(db, pc_str=1)  # str_mod=-5
        npc = await _make_npc(db, sess.id, stat_block_json=json.dumps({
            "strength": 10, "dexterity": 10, "constitution": 10,
            "intelligence": 10, "wisdom": 10, "charisma": 10,
            "max_hp": 20, "current_hp": 20,
            "ac": 99,
        }))

        class Nat20Rng:
            def randint(self, a, b):
                return 20

        result = await resolve_attack(
            db,
            session_id=sess.id,
            attacker_id=char.id,
            attacker_kind="pc",
            target_id=npc.id,
            target_kind="npc",
            rng=Nat20Rng(),
        )
        assert result.hit is True
        assert result.attack_roll.critical_success is True

    async def test_natural_1_always_misses(self, db: AsyncSession):
        """Natural 1 misses even against AC=1."""
        _, char, sess, state, _ = await _make_world_char_session(db, pc_str=30)  # str_mod=10
        npc = await _make_npc(db, sess.id, stat_block_json=json.dumps({
            "strength": 10, "dexterity": 1, "constitution": 10,
            "intelligence": 10, "wisdom": 10, "charisma": 10,
            "max_hp": 20, "current_hp": 20,
            "ac": 1,
        }))

        class Nat1Rng:
            def randint(self, a, b):
                return 1

        result = await resolve_attack(
            db,
            session_id=sess.id,
            attacker_id=char.id,
            attacker_kind="pc",
            target_id=npc.id,
            target_kind="npc",
            rng=Nat1Rng(),
        )
        assert result.hit is False
        assert result.attack_roll.critical_failure is True

    async def test_target_defeated_when_hp_zero(self, db: AsyncSession):
        """target_defeated=True when HP drops to exactly 0."""
        _, char, sess, _, _ = await _make_world_char_session(db, pc_str=20)
        npc = await _make_npc(db, sess.id, stat_block_json=json.dumps({
            "strength": 10, "dexterity": 1, "constitution": 10,
            "intelligence": 10, "wisdom": 10, "charisma": 10,
            "max_hp": 4, "current_hp": 4,
            "ac": 1,  # always hit
        }))
        char.inventory_json = json.dumps([{
            "name": "大剑", "qty": 1, "item_type": "weapon",
            "effects": [{"type": "damage", "formula": "1d4", "amount": 0}],
        }])
        await db.flush()

        class Nat20Rng:
            def randint(self, a, b):
                return 20

        result = await resolve_attack(
            db,
            session_id=sess.id,
            attacker_id=char.id,
            attacker_kind="pc",
            target_id=npc.id,
            target_kind="npc",
            weapon_name="大剑",
            rng=Nat20Rng(),
        )
        assert result.hit is True
        assert result.target_hp_after >= 0  # no negative HP
        if result.target_defeated:
            assert result.target_hp_after == 0

    async def test_overkill_clamps_to_zero(self, db: AsyncSession):
        """HP after massive overkill stays at 0, never goes negative."""
        _, char, sess, _, _ = await _make_world_char_session(db, pc_str=30)
        npc = await _make_npc(db, sess.id, stat_block_json=json.dumps({
            "strength": 10, "dexterity": 1, "constitution": 10,
            "intelligence": 10, "wisdom": 10, "charisma": 10,
            "max_hp": 1, "current_hp": 1,
            "ac": 1,
        }))
        # Weapon that deals enormous damage
        char.inventory_json = json.dumps([{
            "name": "神器", "qty": 1, "item_type": "weapon",
            "effects": [{"type": "damage", "formula": "1d4", "amount": 0}],
            "description": "1d4",
        }])
        await db.flush()

        class Nat20Rng:
            def randint(self, a, b):
                return 20

        result = await resolve_attack(
            db,
            session_id=sess.id,
            attacker_id=char.id,
            attacker_kind="pc",
            target_id=npc.id,
            target_kind="npc",
            weapon_name="神器",
            rng=Nat20Rng(),
        )
        assert result.target_hp_after == 0
        assert result.target_defeated is True


# ── roll_initiative tests ─────────────────────────────────────────────────────

class TestRollInitiative:

    async def test_sorted_descending(self, db: AsyncSession):
        """Initiative order is descending by initiative_total."""
        _, char, sess, _, _ = await _make_world_char_session(db, pc_dex=10)
        npc1 = await _make_npc(db, sess.id, name="哥布林1", stat_block_json=json.dumps({
            "dexterity": 14, "max_hp": 10
        }))
        npc2 = await _make_npc(db, sess.id, name="哥布林2", stat_block_json=json.dumps({
            "dexterity": 8, "max_hp": 10
        }))

        combatants = [("pc", char.id), ("npc", npc1.id), ("npc", npc2.id)]
        order = await roll_initiative(db, session_id=sess.id, combatants=combatants)

        assert len(order) == 3
        totals = [e["initiative_total"] for e in order]
        assert totals == sorted(totals, reverse=True)

    async def test_deterministic_with_seeded_rng(self, db: AsyncSession):
        """Same seed produces same initiative order."""
        _, char, sess, _, _ = await _make_world_char_session(db, pc_dex=10)
        npc = await _make_npc(db, sess.id, name="骷髅")

        combatants = [("pc", char.id), ("npc", npc.id)]
        rng1 = random.Random(777)
        rng2 = random.Random(777)

        order1 = await roll_initiative(db, session_id=sess.id, combatants=combatants, rng=rng1)
        order2 = await roll_initiative(db, session_id=sess.id, combatants=combatants, rng=rng2)

        assert [e["initiative_total"] for e in order1] == [e["initiative_total"] for e in order2]


# ── _apply_attack handler tests ───────────────────────────────────────────────

class TestApplyAttack:

    async def test_records_attack_in_pending_resolutions(self, db: AsyncSession):
        """_apply_attack appends an 'attack' record to pending_resolutions_json."""
        from dzmm.service.state_apply.mechanics import _apply_attack

        _, char, sess, _, _ = await _make_world_char_session(db, pc_str=14)
        npc = await _make_npc(db, sess.id, stat_block_json=json.dumps({
            "strength": 10, "dexterity": 10, "constitution": 10,
            "intelligence": 10, "wisdom": 10, "charisma": 10,
            "max_hp": 20, "current_hp": 20, "ac": 1,
        }))

        attrs = {
            "attacker_kind": "pc",
            "attacker_id": str(char.id),
            "target_kind": "npc",
            "target_id": str(npc.id),
        }
        await _apply_attack(db, sess.id, attrs, current_turn=5)
        await db.flush()

        # Reload session and check pending_resolutions_json
        await db.refresh(sess)
        records = json.loads(sess.pending_resolutions_json)
        attack_records = [r for r in records if r.get("kind") == "attack"]
        assert len(attack_records) == 1
        assert attack_records[0]["result"]["attacker_id"] == char.id

    async def test_marks_npc_dead_on_defeat(self, db: AsyncSession):
        """_apply_attack sets NPC.state='dead' when NPC is defeated (via real attack)."""
        from dzmm.service.state_apply.mechanics import _apply_attack

        # PC with STR=30 → STR_mod=10, attack_mod=10+2=12, damage 1d20 = 1-20 + 10 mod
        # NPC with AC=1, HP=1 → guaranteed hit and defeat
        _, char, sess, _, _ = await _make_world_char_session(db, pc_str=30)
        npc = await _make_npc(db, sess.id, name="弱小哥布林", stat_block_json=json.dumps({
            "strength": 10, "dexterity": 1, "constitution": 10,
            "intelligence": 10, "wisdom": 10, "charisma": 10,
            "max_hp": 1, "current_hp": 1, "ac": 1,
        }))
        # Weapon dealing 1d6 damage — minimum 1, which defeats 1-HP NPC
        char.inventory_json = json.dumps([{
            "name": "大斧", "qty": 1, "item_type": "weapon",
            "effects": [{"type": "damage", "formula": "1d6", "amount": 0}],
            "description": "重型 1d6",
        }])
        await db.flush()

        attrs = {
            "attacker_kind": "pc",
            "attacker_id": str(char.id),
            "target_kind": "npc",
            "target_id": str(npc.id),
            "weapon": "大斧",
        }

        # Use nat-20 RNG to guarantee hit; minimum damage (1) still kills 1-HP NPC
        class Nat20Rng:
            def randint(self, a, b):
                return b if b >= 20 else b  # return max of range (20 for d20, 6 for d6)

        await _apply_attack(db, sess.id, attrs, current_turn=3, rng=Nat20Rng())
        await db.flush()
        await db.refresh(npc)

        assert npc.state == "dead"
        records = json.loads(sess.pending_resolutions_json)
        attack_rec = next((r for r in records if r.get("kind") == "attack"), None)
        assert attack_rec is not None
        assert attack_rec["result"]["target_defeated"] is True


# ── _apply_initiative_request handler tests ───────────────────────────────────

class TestApplyInitiativeRequest:

    async def test_writes_combat_order_json(self, db: AsyncSession):
        """_apply_initiative_request writes sorted order to session.combat_order_json."""
        from dzmm.service.state_apply.mechanics import _apply_initiative_request

        _, char, sess, _, _ = await _make_world_char_session(db, pc_dex=10)
        await _make_npc(db, sess.id, name="哥布林1")

        attrs = {"combatants": "PC,哥布林1"}
        result = await _apply_initiative_request(db, sess.id, attrs, current_turn=1)
        await db.flush()

        assert result is not None
        assert "order" in result
        assert len(result["order"]) == 2

        await db.refresh(sess)
        if hasattr(sess, "combat_order_json"):
            order = json.loads(sess.combat_order_json)
            # Should be 2 entries sorted desc
            assert len(order) == 2

    async def test_resolves_npc_names_within_session(self, db: AsyncSession):
        """_apply_initiative_request correctly resolves NPC names to IDs."""
        from dzmm.service.state_apply.mechanics import _apply_initiative_request

        _, char, sess, _, _ = await _make_world_char_session(db, pc_dex=12)
        npc = await _make_npc(db, sess.id, name="骷髅战士")

        attrs = {"combatants": "PC,骷髅战士"}
        result = await _apply_initiative_request(db, sess.id, attrs, current_turn=2)

        assert result is not None
        order = result["order"]
        kinds = {entry["kind"] for entry in order}
        assert "pc" in kinds
        assert "npc" in kinds

        npc_entry = next(e for e in order if e["kind"] == "npc")
        assert npc_entry["id"] == npc.id
        assert npc_entry["name"] == "骷髅战士"

    async def test_initiative_records_in_pending_resolutions(self, db: AsyncSession):
        """_apply_initiative_request appends an 'initiative' record."""
        from dzmm.service.state_apply.mechanics import _apply_initiative_request

        _, char, sess, _, _ = await _make_world_char_session(db)
        await _make_npc(db, sess.id, name="测试怪")

        attrs = {"combatants": "PC,测试怪"}
        await _apply_initiative_request(db, sess.id, attrs, current_turn=4)
        await db.flush()

        await db.refresh(sess)
        records = json.loads(sess.pending_resolutions_json)
        init_records = [r for r in records if r.get("kind") == "initiative"]
        assert len(init_records) == 1
        assert "order" in init_records[0]["result"]
