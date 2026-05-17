"""v0.15 mechanical engine smoke demo.

Drives a fake session through 3 turns by calling state_apply handlers
directly with constructed tag attrs (no LLM, no SSE). Prints the
pending_resolutions_json + character state after each turn so we can
eyeball whether the engine is actually doing its job.

Run:
    cd backend && python scripts/smoke_v15_engine.py
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    Character,
    CharState,
    ModelConfig,
    NPC,
    Session as GameSession,
    World,
)
from dzmm.engine.schema import Item, ItemEffect
from dzmm.service.state_apply.mechanics import (
    _apply_attack,
    _apply_dice_request,
    _apply_initiative_request,
    _apply_item_use,
    _apply_skill_request,
)


def _hr(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


async def _seed(s) -> tuple[GameSession, Character, NPC]:
    world = World(name="哥布林洞穴", content_md="阴森的地下网络", style="dark fantasy")
    s.add(world)
    await s.flush()

    sword = Item(
        name="短剑",
        qty=1,
        item_type="weapon",
        effects=[
            ItemEffect(type="damage", formula="1d6+STR"),
        ],
        description="一把锋利的钢制短剑",
    )
    leather = Item(
        name="皮甲",
        qty=1,
        item_type="armor",
        effects=[ItemEffect(type="armor_bonus", amount=2)],
        description="厚实的皮甲",
    )
    potion = Item(
        name="治疗药水",
        qty=2,
        item_type="consumable",
        effects=[ItemEffect(type="heal_hp", amount=15)],
        description="红色的小瓶子，恢复 HP",
    )
    notebook = Item(
        name="侦探笔记本",
        qty=1,
        item_type="quest",
        effects=[],
        description="记录线索的小本子",
    )

    inv_json = json.dumps([sword.model_dump(), leather.model_dump(),
                            potion.model_dump(), notebook.model_dump()])
    skills_json = json.dumps({"潜行": 50, "调查": 65, "近战": 40, "察言观色": 35})
    equip_json = json.dumps({"weapon": "短剑", "armor": "皮甲"})

    char = Character(
        world_id=world.id,
        name="张墨衍",
        profile_md="经验丰富的私家侦探",
        base_stats_json="{}",
        strength=12,         # +1
        dexterity=15,        # +2
        constitution=13,     # +1
        intelligence=15,     # +2
        wisdom=14,           # +2
        charisma=11,         # +0
        max_hp=30,
        max_sanity=50,
        max_stamina=30,
        skills_json=skills_json,
        inventory_json=inv_json,
        equipment_json=equip_json,
    )
    s.add(char)

    cfg = ModelConfig(name="stub", type="ollama",
                      base_url="http://localhost", model_name="stub")
    s.add(cfg)
    await s.flush()

    sess = GameSession(
        name="洞穴探险",
        world_id=world.id,
        character_id=char.id,
        gm_model_config_id=cfg.id,
        summarizer_model_config_id=cfg.id,
    )
    s.add(sess)
    await s.flush()

    state = CharState(
        session_id=sess.id,
        stats_json=json.dumps({"hp": 30, "sanity": 50}),
        stamina=30,
    )
    s.add(state)

    # Seed a goblin NPC for combat demo
    goblin_stats = {
        "strength": 10, "dexterity": 12, "constitution": 10,
        "max_hp": 12, "current_hp": 12, "ac": 11,
        "weapon_formula": "1d6",
    }
    goblin = NPC(
        session_id=sess.id,
        name="哥布林斥候",
        state="alive",
        favor=-50,
        stat_block_json=json.dumps(goblin_stats),
    )
    s.add(goblin)

    await s.commit()
    return sess, char, goblin


def _show_state(label: str, char: Character, state: CharState) -> None:
    inv = json.loads(char.inventory_json)
    stats = json.loads(state.stats_json)
    print(f"\n--- {label} ---")
    print(f"  HP {stats.get('hp')}/{char.max_hp}   "
          f"SAN {stats.get('sanity')}/{char.max_sanity}   "
          f"STA {state.stamina}/{char.max_stamina}")
    inv_strs = [f"{it['name']}×{it['qty']}" for it in inv]
    print(f"  背包: {', '.join(inv_strs) if inv_strs else '空'}")


def _show_pending(sess: GameSession) -> None:
    records = json.loads(sess.pending_resolutions_json or "[]")
    if not records:
        print("  (无机械结算记录)")
        return
    print("  本回合机械结算:")
    for r in records:
        kind = r["kind"]
        inp = r.get("input", {})
        res = r.get("result", {})
        if kind == "dice":
            rolls = res.get("rolls", [])
            mod = res.get("modifier", 0)
            total = res.get("total")
            formula = inp.get("formula", "?")
            purpose = inp.get("purpose", "")
            print(f"    🎲 {purpose}（{formula}）: {rolls}+{mod} = {total}")
        elif kind == "skill":
            skill = inp.get("skill", "?")
            d20 = res.get("d20")
            total = res.get("total")
            dc = res.get("dc")
            succ = "✅ 成功" if res.get("succeeded") else "❌ 失败"
            crit = res.get("crit", False)
            extra = " 🌟大成功" if crit and res.get("succeeded") else \
                    (" 💥大失败" if crit else "")
            print(f"    🎯 {skill} d20={d20} → {total} vs DC{dc} → {succ}{extra}")
        elif kind == "item":
            item = inp.get("item_name", "?")
            applied = res.get("applied_effects", [])
            print(f"    🧪 用了「{item}」: {applied}")
        elif kind == "attack":
            attacker = inp.get("attacker_id")
            target = inp.get("target_id")
            d20 = res.get("d20")
            atk_total = res.get("attack_total")
            ac = res.get("ac")
            hit = res.get("hit")
            dmg_rolls = res.get("damage_rolls")
            dmg_mod = res.get("damage_mod")
            dmg = res.get("damage_total", 0)
            hp_b = res.get("target_hp_before")
            hp_a = res.get("target_hp_after")
            defeated = res.get("target_defeated", False)
            outcome = "命中" if hit else "未命中"
            defeat = " ☠️击败" if defeated else ""
            dmg_str = f" 伤害 {dmg_rolls}+{dmg_mod}={dmg}（HP {hp_b}→{hp_a}）" if hit else ""
            print(f"    ⚔️ id{attacker}→id{target} d20={d20}+_ ={atk_total} "
                  f"vs AC{ac} → {outcome}{dmg_str}{defeat}")
        elif kind == "initiative":
            order = res.get("order", [])
            chain = " → ".join(
                f"{c.get('name','?')}({c.get('initiative_total','?')})"
                for c in order)
            print(f"    🪄 先攻: {chain}")
        else:
            print(f"    ?? {kind}: {res}")


async def _refetch(db) -> tuple[GameSession, Character, CharState]:
    """Refresh ORM objects from DB after handler writes."""
    sess = (await db.execute(
        __import__("sqlalchemy").select(GameSession).limit(1))).scalar_one()
    char = (await db.execute(
        __import__("sqlalchemy").select(Character).limit(1))).scalar_one()
    state = (await db.execute(
        __import__("sqlalchemy").select(CharState).limit(1))).scalar_one()
    return sess, char, state


async def _clear_pending(db, sess: GameSession) -> None:
    """Simulate end-of-turn: clear pending_resolutions for next turn."""
    sess.pending_resolutions_json = "[]"
    await db.commit()


async def main() -> None:
    tmp = tempfile.mkdtemp(prefix="dzmm-smoke-")
    db_path = Path(tmp) / "smoke.db"
    engine = get_engine(f"sqlite+aiosqlite:///{db_path}")
    await init_db(engine)

    SessionMaker = async_session(engine)
    async with SessionMaker() as db:
        sess, char, goblin = await _seed(db)
        session_id = sess.id
        char_id = char.id
        goblin_id = goblin.id

        _hr("🎬 SETUP — 张墨衍 vs 哥布林斥候")
        print(f"  角色: {char.name}")
        print(f"  属性: STR {char.strength} DEX {char.dexterity} CON {char.constitution} "
              f"INT {char.intelligence} WIS {char.wisdom} CHA {char.charisma}")
        print(f"  技能: {json.loads(char.skills_json)}")
        print(f"  装备: {json.loads(char.equipment_json)}")
        from sqlalchemy import select as _sel
        _initial_state = (await db.execute(
            _sel(CharState).where(CharState.session_id == session_id))).scalar_one()
        _show_state("初始状态", char, _initial_state)

        # ── 回合 1: 潜行检定 + 投伤害骰子 ──
        _hr("回合 1: GM 让玩家做潜行检定 + 摸一下黑暗中物体（伤害骰）")
        print("  GM 输出: <skill_request skill='潜行' attribute='dexterity' dc='14'/>")
        print("  GM 输出: <dice_request formula='2d6+3' purpose='陷阱伤害'/>")
        await _apply_skill_request(db, session_id,
            {"skill": "潜行", "attribute": "dexterity", "dc": "14"}, 1)
        await _apply_dice_request(db, session_id,
            {"formula": "2d6+3", "purpose": "陷阱伤害"}, 1)
        await db.commit()
        sess, char, state = await _refetch(db)
        _show_pending(sess)

        # ── 回合 2: 用治疗药水 ──
        await _clear_pending(db, sess)
        _hr("回合 2: 玩家受伤后用治疗药水")
        # First inflict damage to PC
        stats = json.loads(state.stats_json)
        stats["hp"] = 18  # took some damage off-screen
        state.stats_json = json.dumps(stats)
        await db.commit()
        sess, char, state = await _refetch(db)
        _show_state("受伤后", char, state)

        print("  GM 输出: <item_use item_name='治疗药水'/>")
        await _apply_item_use(db, session_id,
            {"item_name": "治疗药水", "actor": "PC"}, 2)
        await db.commit()
        sess, char, state = await _refetch(db)
        _show_pending(sess)
        _show_state("使用治疗药水后", char, state)

        # ── 回合 3: 战斗开始 - 先攻 + 攻击 ──
        await _clear_pending(db, sess)
        _hr("回合 3: 战斗触发 - 先攻 + 玩家攻击哥布林")
        print(f"  GM 输出: <initiative_request combatants='PC,哥布林斥候'/>")
        await _apply_initiative_request(db, session_id,
            {"combatants": "PC,哥布林斥候"}, 3)
        print(f"  GM 输出: <attack attacker_kind='pc' attacker_id='{char_id}' "
              f"target_kind='npc' target_id='{goblin_id}' weapon='短剑'/>")
        await _apply_attack(db, session_id, {
            "attacker_kind": "pc", "attacker_id": str(char_id),
            "target_kind": "npc", "target_id": str(goblin_id),
            "weapon": "短剑",
        }, 3)
        await db.commit()
        sess, char, state = await _refetch(db)
        _show_pending(sess)

        # Refresh goblin state
        from sqlalchemy import select
        goblin_now = (await db.execute(
            select(NPC).where(NPC.id == goblin_id))).scalar_one()
        gob_stats = json.loads(goblin_now.stat_block_json)
        print(f"\n  哥布林斥候 HP {gob_stats.get('current_hp','?')}/{gob_stats.get('max_hp','?')} "
              f"state={goblin_now.state}")

        # ── 回合 4: 继续打 ──
        await _clear_pending(db, sess)
        _hr("回合 4: 再砍一刀（看大成功/大失败概率）")
        for i in range(3):
            print(f"\n  尝试 #{i+1}:")
            await _apply_attack(db, session_id, {
                "attacker_kind": "pc", "attacker_id": str(char_id),
                "target_kind": "npc", "target_id": str(goblin_id),
                "weapon": "短剑",
            }, 4)
            await db.commit()
            sess, char, state = await _refetch(db)
            _show_pending(sess)
            await _clear_pending(db, sess)
            goblin_now = (await db.execute(
                select(NPC).where(NPC.id == goblin_id))).scalar_one()
            gob_stats = json.loads(goblin_now.stat_block_json)
            print(f"    哥布林 HP {gob_stats.get('current_hp','?')}/{gob_stats.get('max_hp','?')} "
                  f"state={goblin_now.state}")
            if goblin_now.state == "dead":
                break

        _hr("✅ Demo 完成")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
