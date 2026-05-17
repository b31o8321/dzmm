"""v0.15 engine stress demo — large-sample distribution + multi-encounter session.

Runs 4 separate "playtest" scenarios to validate engine on volume:
  1. Pure d20 distribution — 200 rolls, histogram
  2. Skill check at varied DC — 100 rolls per DC level, success rate curve
  3. Combat hit/damage distribution — 100 attacks, mean / min / max / crit rate
  4. Full multi-encounter session — 15-turn adventure with skill + combat + healing

Run: cd backend && python scripts/smoke_v15_stress.py
"""
from __future__ import annotations

import asyncio
import json
import random
import statistics
import tempfile
from collections import Counter
from pathlib import Path

from sqlalchemy import select

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    Character, CharState, ModelConfig, NPC, Session as GameSession, World,
)
from dzmm.engine.combat import resolve_attack, roll_initiative
from dzmm.engine.dice import roll, skill_check, get_modifier
from dzmm.engine.schema import Item, ItemEffect
from dzmm.service.state_apply.mechanics import (
    _apply_attack, _apply_dice_request, _apply_initiative_request,
    _apply_item_use, _apply_skill_request,
)


def hr(t: str) -> None:
    print(f"\n{'─' * 72}\n  {t}\n{'─' * 72}")


# ── Scenario 1: pure d20 distribution ───────────────────────────────
def scenario_1_dice_distribution(n: int = 500) -> None:
    hr(f"场景 1: {n} 次 d20 真随机骰子分布")
    rolls = [roll("d20").total for _ in range(n)]
    hist = Counter(rolls)
    bar_max = max(hist.values())
    print("  d20  次数   占比     bar")
    for v in range(1, 21):
        c = hist[v]
        pct = c / n * 100
        bar = "█" * int(c / bar_max * 40)
        marker = " ⭐" if v == 20 else (" 💥" if v == 1 else "")
        print(f"  {v:>3}  {c:>4}  {pct:>5.1f}%  {bar}{marker}")
    print(f"\n  均值={statistics.mean(rolls):.2f}（理论 10.50）"
          f"  方差={statistics.variance(rolls):.2f}（理论 ~33.25）")
    print(f"  Nat 20: {hist[20]}/{n} = {hist[20]/n*100:.1f}%（理论 5%）"
          f"  Nat 1: {hist[1]}/{n} = {hist[1]/n*100:.1f}%（理论 5%）")


# ── Scenario 2: skill check at varied DC ────────────────────────────
def scenario_2_skill_curve(n: int = 200) -> None:
    hr(f"场景 2: 技能检定成功率曲线（DEX 15 → +2，潜行 50 → +5）")
    print(f"  每个 DC 跑 {n} 次")
    print(f"  d20 + 2 (DEX) + 5 (潜行) = 期望平均 17.5")
    print(f"  DC    成功率   crit成功   crit失败")
    for dc in [8, 10, 12, 14, 16, 18, 20, 22, 25]:
        results = [skill_check(attribute_value=15, skill_level=50, dc=dc)
                   for _ in range(n)]
        succ = sum(1 for r in results if r.succeeded)
        crit_s = sum(1 for r in results if r.crit and r.succeeded)
        crit_f = sum(1 for r in results if r.crit and not r.succeeded)
        bar = "█" * int(succ / n * 40)
        print(f"  {dc:>3}  {succ/n*100:>5.1f}%   {crit_s/n*100:>5.1f}%   "
              f"{crit_f/n*100:>5.1f}%   {bar}")


# ── Scenario 3: combat hit/damage distribution ──────────────────────
async def scenario_3_combat_distribution(n: int = 200) -> None:
    hr(f"场景 3: 战斗命中 + 伤害分布（{n} 次攻击，无脏腑数据库写入）")
    print(f"  攻击方: STR 14 (+2), prof 2, 短剑 1d8+STR (总 atk_mod=+4)")
    print(f"  防守方: AC 13, HP 1000（足够吃所有攻击）")

    # set up minimal in-memory state to drive resolve_attack
    tmp = tempfile.mkdtemp(prefix="dzmm-stress-")
    engine = get_engine(f"sqlite+aiosqlite:///{tmp}/db.sqlite")
    await init_db(engine)
    SM = async_session(engine)
    async with SM() as db:
        w = World(name="x", content_md="", style="x")
        db.add(w); await db.flush()
        sword = Item(name="短剑", qty=1, item_type="weapon",
                     effects=[ItemEffect(type="damage", formula="1d8+STR")])
        char = Character(
            world_id=w.id, name="A", profile_md="x", base_stats_json="{}",
            strength=14, dexterity=10, max_hp=30, max_sanity=30, max_stamina=30,
            inventory_json=json.dumps([sword.model_dump()]),
            equipment_json=json.dumps({"weapon": "短剑"}),
        )
        db.add(char)
        cfg = ModelConfig(name="x", type="ollama", base_url="x", model_name="x")
        db.add(cfg); await db.flush()
        sess = GameSession(name="x", world_id=w.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id)
        db.add(sess); await db.flush()
        cs = CharState(session_id=sess.id, stats_json=json.dumps({"hp": 30, "sanity": 30}), stamina=30)
        db.add(cs)
        npc = NPC(session_id=sess.id, name="Dummy", state="alive",
                  stat_block_json=json.dumps({
                      "strength": 10, "max_hp": 1000, "current_hp": 1000,
                      "ac": 13, "weapon_formula": "1d4"}))
        db.add(npc); await db.commit()
        npc_id = npc.id; char_id = char.id; sid = sess.id

        hits = 0
        crits = 0
        misses_nat1 = 0
        damages = []
        for _ in range(n):
            r = await resolve_attack(
                db, session_id=sid,
                attacker_id=char_id, attacker_kind="pc",
                target_id=npc_id, target_kind="npc",
                weapon_name="短剑",
            )
            if r.hit:
                hits += 1
                damages.append(r.damage_dealt)
                if r.attack_roll.critical_success:
                    crits += 1
            elif r.attack_roll.critical_failure:
                misses_nat1 += 1

        await engine.dispose()

    print(f"\n  命中率: {hits}/{n} = {hits/n*100:.1f}%")
    print(f"  Nat 20 (强制命中): {crits}/{n} = {crits/n*100:.1f}%")
    print(f"  Nat 1 (强制未命中): {misses_nat1}/{n} = {misses_nat1/n*100:.1f}%")
    if damages:
        print(f"  伤害分布 (1d8+2):")
        print(f"    min={min(damages)}  max={max(damages)}  "
              f"mean={statistics.mean(damages):.2f}（理论 6.5）  "
              f"median={statistics.median(damages)}")
        dh = Counter(damages)
        bar_max = max(dh.values())
        for d in range(3, 11):  # 1d8+2 → 3..10
            c = dh.get(d, 0)
            bar = "█" * int(c / bar_max * 30) if bar_max else ""
            print(f"    {d:>2}: {c:>3}  {bar}")


# ── Scenario 4: full multi-encounter session ────────────────────────
async def scenario_4_full_session(turns: int = 15) -> None:
    hr(f"场景 4: 完整 {turns} 回合冒险（侦探 + 战斗 + 治疗）")

    tmp = tempfile.mkdtemp(prefix="dzmm-full-")
    engine = get_engine(f"sqlite+aiosqlite:///{tmp}/db.sqlite")
    await init_db(engine)
    SM = async_session(engine)
    async with SM() as db:
        w = World(name="阴影城", content_md="", style="noir")
        db.add(w); await db.flush()
        sword = Item(name="短剑", qty=1, item_type="weapon",
                     effects=[ItemEffect(type="damage", formula="1d6+STR")])
        leather = Item(name="皮甲", qty=1, item_type="armor",
                       effects=[ItemEffect(type="armor_bonus", amount=2)])
        potions = Item(name="治疗药水", qty=3, item_type="consumable",
                       effects=[ItemEffect(type="heal_hp", amount=10)])
        char = Character(
            world_id=w.id, name="侦探陈", profile_md="x", base_stats_json="{}",
            strength=13, dexterity=15, constitution=12,
            intelligence=15, wisdom=14, charisma=11,
            max_hp=24, max_sanity=60, max_stamina=20,
            skills_json=json.dumps({"调查": 65, "潜行": 50, "近战": 40, "察言观色": 45}),
            inventory_json=json.dumps([sword.model_dump(), leather.model_dump(), potions.model_dump()]),
            equipment_json=json.dumps({"weapon": "短剑", "armor": "皮甲"}),
        )
        db.add(char)
        cfg = ModelConfig(name="x", type="ollama", base_url="x", model_name="x")
        db.add(cfg); await db.flush()
        sess = GameSession(name="阴影城调查", world_id=w.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id)
        db.add(sess); await db.flush()
        cs = CharState(session_id=sess.id,
                       stats_json=json.dumps({"hp": 24, "sanity": 60}), stamina=20)
        db.add(cs)
        # Three goblins for the encounter
        goblins = []
        for i, name in enumerate(["哥布林斥候", "哥布林战士", "哥布林萨满"]):
            ac = 11 + i  # 11, 12, 13
            hp = 8 + i*3  # 8, 11, 14
            g = NPC(session_id=sess.id, name=name, state="alive",
                    favor=-50,
                    stat_block_json=json.dumps({
                        "strength": 10, "dexterity": 12, "max_hp": hp, "current_hp": hp,
                        "ac": ac, "weapon_formula": "1d6"}))
            db.add(g); goblins.append(g)
        await db.commit()
        sid = sess.id; char_id = char.id

        # Scripted scene per turn
        scenarios = [
            ("调查血迹", "skill", {"skill": "调查", "attribute": "wisdom", "dc": "12"}),
            ("潜行进入巷子", "skill", {"skill": "潜行", "attribute": "dexterity", "dc": "14"}),
            ("察言观色判断NPC", "skill", {"skill": "察言观色", "attribute": "wisdom", "dc": "15"}),
            ("跳过断桥", "dice", {"formula": "d20", "purpose": "命运"}),
            ("战斗开始 (先攻)", "init", {}),
            ("攻击哥布林1", "attack", {"target_idx": 0}),
            ("攻击哥布林1", "attack", {"target_idx": 0}),
            ("用治疗药水", "item", {"item_name": "治疗药水"}),
            ("攻击哥布林2", "attack", {"target_idx": 1}),
            ("攻击哥布林2", "attack", {"target_idx": 1}),
            ("攻击哥布林2", "attack", {"target_idx": 1}),
            ("攻击哥布林3", "attack", {"target_idx": 2}),
            ("用治疗药水", "item", {"item_name": "治疗药水"}),
            ("攻击哥布林3", "attack", {"target_idx": 2}),
            ("攻击哥布林3", "attack", {"target_idx": 2}),
        ]

        summary_lines = []
        for t in range(1, turns + 1):
            scene_idx = (t - 1) % len(scenarios)
            label, kind, args = scenarios[scene_idx]
            sess_row = (await db.execute(select(GameSession).where(GameSession.id == sid))).scalar_one()
            sess_row.pending_resolutions_json = "[]"  # clear each turn
            await db.commit()

            if kind == "skill":
                await _apply_skill_request(db, sid, args, t)
            elif kind == "dice":
                await _apply_dice_request(db, sid, args, t)
            elif kind == "item":
                await _apply_item_use(db, sid, args, t)
            elif kind == "init":
                names = "侦探陈," + ",".join(g.name for g in goblins if g.state == "alive")
                await _apply_initiative_request(db, sid, {"combatants": names}, t)
            elif kind == "attack":
                idx = args["target_idx"]
                if idx < len(goblins) and goblins[idx].state == "alive":
                    await _apply_attack(db, sid, {
                        "attacker_kind": "pc", "attacker_id": str(char_id),
                        "target_kind": "npc", "target_id": str(goblins[idx].id),
                        "weapon": "短剑",
                    }, t)
                else:
                    summary_lines.append(f"T{t:>2} [{label}] 目标已倒下，跳过")
                    continue
            await db.commit()

            # Read back and format
            sess_row = (await db.execute(select(GameSession).where(GameSession.id == sid))).scalar_one()
            cs_row = (await db.execute(select(CharState).where(CharState.session_id == sid))).scalar_one()
            recs = json.loads(sess_row.pending_resolutions_json or "[]")
            stats = json.loads(cs_row.stats_json or "{}")
            char_row = (await db.execute(select(Character).where(Character.id == char_id))).scalar_one()
            inv = json.loads(char_row.inventory_json or "[]")
            inv_brief = ",".join(f"{i['name']}×{i['qty']}" for i in inv)
            for r in recs:
                rk = r["kind"]
                res = r["result"]
                if rk == "skill":
                    line = f"🎯{r['input']['skill']} {res['d20']}→{res['total']} vs DC{res['dc']} {'✅' if res['succeeded'] else '❌'}"
                elif rk == "dice":
                    line = f"🎲{r['input'].get('purpose','?')}({r['input']['formula']}) = {res['total']}"
                elif rk == "item":
                    line = f"🧪{r['input']['item_name']} → {res.get('applied_effects', [])}"
                elif rk == "initiative":
                    line = f"🪄先攻 " + " > ".join(f"{c['name']}({c['initiative_total']})" for c in res['order'])
                elif rk == "attack":
                    hit = "✅命中" if res['hit'] else "❌未命中"
                    extra = f" 伤害{res['damage_total']}（HP {res['target_hp_before']}→{res['target_hp_after']}）" + (" ☠️" if res['target_defeated'] else "") if res['hit'] else ""
                    line = f"⚔️攻击 d20={res['d20']} vs AC{res['ac']} {hit}{extra}"
                else:
                    line = f"?{rk}"
                summary_lines.append(f"T{t:>2} [{label:<14}] {line}  | PC HP {stats.get('hp')} | {inv_brief}")

        await engine.dispose()

    print(f"  {'回合':<5} {'场景':<16} 结算\n")
    for ln in summary_lines:
        print(f"  {ln}")


async def main() -> None:
    # Scenario 1 & 2 are pure-function, no DB
    scenario_1_dice_distribution(n=500)
    scenario_2_skill_curve(n=200)
    # Scenario 3 hits DB
    await scenario_3_combat_distribution(n=200)
    # Scenario 4 full session
    await scenario_4_full_session(turns=15)
    print(f"\n{'═' * 72}\n  ✅ 全部 4 场景完成\n{'═' * 72}\n")


if __name__ == "__main__":
    random.seed()  # actual entropy
    asyncio.run(main())
