"""Live playtest of v0.15 against real Ollama LLM.

Drives 6 scripted turns through dzmm.service.game.run_turn() with a
real qwen2.5:7b model. Captures narrative, emitted tags, mechanic
resolutions. After the run, dumps a structured observation file so
we can analyze what worked and what didn't.

Run: cd backend && python scripts/playtest_v15_live.py
Requires: Ollama running at localhost:11434 with qwen2.5:7b
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import traceback
from collections import Counter
from pathlib import Path

# Patch APP_DIR before importing dzmm so the script uses a temp dir
_tmp = tempfile.mkdtemp(prefix="dzmm-playtest-")
os.environ["HOME"] = _tmp

from sqlalchemy import select

from dzmm.config import APP_DIR
from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    Character, CharState, ModelConfig, NPC, Session as GameSession, World,
)
from dzmm.engine.genre_templates import apply_genre_template
from dzmm.engine.schema import Item
from dzmm.models.ollama import OllamaClient
from dzmm.models.client import GenerationParams
from dzmm.parsing.events import NarrativeDelta, TagComplete, UsageSummary
from dzmm.service.game import run_turn


# ───────────────────────────────────────────────────────────────
# Setup
# ───────────────────────────────────────────────────────────────

async def seed(db) -> tuple[GameSession, Character]:
    world = World(
        name="阴影城",
        content_md="""# 阴影城

一座永远笼罩在浓雾中的港口城市，雨水滴答个不停。
霓虹招牌的光线穿过雾气在湿漉漉的街道上模糊扭曲。
警察局腐败，地下势力林立，每一个角落都可能藏着秘密。

# 关键地点
- 警察局：堕落的官僚机构，警长拒绝深入调查
- 红灯区"潮湿酒吧"：消息和危险交汇的地方
- 雨夜码头：货物和尸体常出现的地方
- 旧公寓：侦探的栖身之所
""",
        style="noir",
    )
    db.add(world)
    await db.flush()

    # Use the genre template for 悬疑探案
    template = apply_genre_template("悬疑探案")
    stat_block = template["stat_block"]
    skills = template["skills"]
    inventory = template["inventory"]

    char = Character(
        world_id=world.id,
        name="陈墨衍",
        profile_md="""# 陈墨衍 — 私家侦探

35 岁，前警员，因为不肯配合伪造证据被开除。在旧公寓的二楼开了一家
单人侦探事务所。脾气倔强，香烟不离手，偏爱搜集线索胜过动用武力。

擅长：现场调查、识别说谎、街头人脉
弱点：脾气暴躁、不善社交、健康每况愈下
""",
        gender="male",
        base_stats_json="{}",
        strength=stat_block["strength"],
        dexterity=stat_block["dexterity"],
        constitution=stat_block["constitution"],
        intelligence=stat_block["intelligence"],
        wisdom=stat_block["wisdom"],
        charisma=stat_block["charisma"],
        max_hp=stat_block["max_hp"],
        max_sanity=stat_block["max_sanity"],
        max_stamina=stat_block["max_stamina"],
        skills_json=json.dumps(skills),
        inventory_json=json.dumps(inventory),
        equipment_json=json.dumps({}),
    )
    db.add(char)

    cfg = ModelConfig(
        name="qwen2.5:7b",
        type="ollama",
        base_url="http://localhost:11434",
        model_name="qwen2.5:7b",
        timeout=120.0,
    )
    db.add(cfg)
    await db.flush()

    sess = GameSession(
        name="雨夜的尸体",
        world_id=world.id,
        character_id=char.id,
        gm_model_config_id=cfg.id,
        summarizer_model_config_id=cfg.id,
        settings_json=json.dumps({"debug_mode": True, "use_v10": False}),
    )
    db.add(sess)
    await db.flush()

    cs = CharState(
        session_id=sess.id,
        stats_json=json.dumps({"hp": stat_block["max_hp"], "sanity": stat_block["max_sanity"]}),
        stamina=stat_block["max_stamina"],
    )
    db.add(cs)

    await db.commit()
    return sess, char


# ───────────────────────────────────────────────────────────────
# Run one turn, capture all events
# ───────────────────────────────────────────────────────────────

async def run_one_turn(db, session_id: int, action: str, client) -> dict:
    narrative = []
    tags: list[TagComplete] = []
    usage = None
    err = None
    try:
        async for ev in run_turn(
            session=db,
            session_id=session_id,
            user_action=action,
            client=client,
            params=GenerationParams(temperature=0.7, max_tokens=600),
        ):
            if isinstance(ev, NarrativeDelta):
                narrative.append(ev.text)
            elif isinstance(ev, TagComplete):
                tags.append(ev)
            elif isinstance(ev, UsageSummary):
                usage = (ev.tokens_in, ev.tokens_out)
        await db.commit()
    except Exception as e:
        err = str(e) + "\n" + traceback.format_exc()
        await db.rollback()

    return {
        "narrative": "".join(narrative),
        "tags": [(t.name, dict(t.attrs)) for t in tags],
        "tokens": usage,
        "error": err,
    }


def _read_state(db_sync, session_id: int) -> dict:
    """Read current state. db_sync = the same AsyncSession (we await separately)."""
    raise NotImplementedError  # use _read_state_async


async def _read_state_async(db, session_id: int, character_id: int) -> dict:
    sess = await db.get(GameSession, session_id)
    cs = (await db.execute(select(CharState).where(CharState.session_id == session_id))).scalar_one()
    char = await db.get(Character, character_id)
    npcs = (await db.execute(select(NPC).where(NPC.session_id == session_id))).scalars().all()
    return {
        "turn_count": sess.turn_count,
        "doom": sess.doom_score,
        "hp": json.loads(cs.stats_json).get("hp"),
        "sanity": json.loads(cs.stats_json).get("sanity"),
        "stamina": cs.stamina,
        "pending_resolutions": json.loads(sess.pending_resolutions_json or "[]"),
        "npc_count": len(npcs),
        "npc_summary": [
            {"name": n.name, "state": n.state, "favor": n.favor,
             "location": n.current_location or "?"} for n in npcs[:5]
        ],
        "inventory": json.loads(char.inventory_json or "[]"),
    }


# ───────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────

ACTIONS = [
    "环顾四周，先看清楚我现在在哪里。",
    "走到酒吧门口，仔细观察周围有什么可疑的人。",
    "走进酒吧，找一个看起来眼线多的人搭话，问问最近码头的怪事。",
    "请那个酒鬼喝一杯，套出他知道的事。",
    "顺着他指的方向，去雨夜码头查看尸体。",
    "我蹲下检查尸体身上的口袋和伤口。",
]


async def main() -> None:
    db_path = Path(_tmp) / "playtest.db"
    engine = get_engine(f"sqlite+aiosqlite:///{db_path}")
    await init_db(engine)
    SM = async_session(engine)

    async with SM() as db:
        sess, char = await seed(db)
        client = OllamaClient(
            name="qwen2.5:7b",
            base_url="http://localhost:11434",
            model="qwen2.5:7b",
            timeout=600.0,
        )

        # Warm-up call so cold-start latency doesn't blow up the first turn
        print("⏳ 预热 LLM（首次加载模型...）", flush=True)
        from dzmm.models.client import Message
        try:
            async for _ in client.stream(
                [Message(role="user", content="hi")],
                GenerationParams(temperature=0.1, max_tokens=4),
            ):
                pass
            print("✅ LLM 预热完成")
        except Exception as e:
            print(f"⚠️ 预热失败: {e}")

        print(f"╔══════════════════════════════════════════════════════════════════════╗")
        print(f"║ Playtest: {sess.name}")
        print(f"║ 角色: {char.name} | STR={char.strength} DEX={char.dexterity} "
              f"CON={char.constitution} INT={char.intelligence} WIS={char.wisdom} CHA={char.charisma}")
        print(f"║ HP/SAN/STA = {char.max_hp}/{char.max_sanity}/{char.max_stamina}")
        print(f"║ 技能: {json.loads(char.skills_json)}")
        inv = json.loads(char.inventory_json)
        print(f"║ 起始物品: {[i['name']+'×'+str(i['qty']) for i in inv]}")
        print(f"╚══════════════════════════════════════════════════════════════════════╝")

        # Track aggregate stats
        all_tags = []
        total_tokens = [0, 0]
        new_v15_tag_uses = Counter()
        legacy_tag_uses = Counter()
        V15_TAGS = {"dice_request", "skill_request", "item_use", "attack",
                    "initiative_request"}

        for i, action in enumerate(ACTIONS, 1):
            print(f"\n{'━' * 72}")
            print(f"【回合 {i}】玩家行动: {action}")
            print(f"{'━' * 72}")

            result = await run_one_turn(db, sess.id, action, client)
            if result["error"]:
                print(f"❌ 错误: {result['error']}")
                break

            # Print narrative (truncated)
            narr = result["narrative"].strip()
            print(f"\n📖 GM 叙事 ({len(narr)} chars):")
            print(narr[:1200] + ("…" if len(narr) > 1200 else ""))

            # Tags grouped
            tagcounts = Counter(t[0] for t in result["tags"])
            print(f"\n🏷️  本回合标签: {dict(tagcounts)}")
            for tn, attrs in result["tags"]:
                if tn in V15_TAGS:
                    new_v15_tag_uses[tn] += 1
                elif tn != "narrative":
                    legacy_tag_uses[tn] += 1
                if tn != "narrative":
                    a = ", ".join(f"{k}={v!r}" for k, v in list(attrs.items())[:5])
                    print(f"    <{tn} {a}/>")

            all_tags.extend(result["tags"])
            if result["tokens"]:
                total_tokens[0] += result["tokens"][0]
                total_tokens[1] += result["tokens"][1]
                print(f"\n📊 tokens: ↑{result['tokens'][0]} ↓{result['tokens'][1]}")

            # State after turn
            st = await _read_state_async(db, sess.id, char.id)
            print(f"\n📍 状态: HP={st['hp']} SAN={st['sanity']} STA={st['stamina']} "
                  f"doom={st['doom']} 回合={st['turn_count']} NPCs={st['npc_count']}")
            if st["pending_resolutions"]:
                print(f"⚙️  机械结算 ({len(st['pending_resolutions'])} 条):")
                for r in st["pending_resolutions"][-3:]:
                    print(f"    {r['kind']}: in={r['input']}  res={r['result']}")
            if st["npc_summary"]:
                print(f"👥 NPC: {st['npc_summary']}")

        # Aggregate report
        print(f"\n{'═' * 72}")
        print("【全程统计】")
        print(f"{'═' * 72}")
        print(f"总 tokens: ↑{total_tokens[0]} ↓{total_tokens[1]}")
        print(f"\nv0.15 新标签使用: {dict(new_v15_tag_uses)}")
        print(f"老标签使用: {dict(legacy_tag_uses)}")

        # Dump full transcript to file
        out = Path(_tmp) / "transcript.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump({
                "tags": all_tags,  # already serialized as (name, attrs) tuples
                "v15_uses": dict(new_v15_tag_uses),
                "legacy_uses": dict(legacy_tag_uses),
                "tokens": total_tokens,
            }, f, ensure_ascii=False, indent=2)
        print(f"\n完整 transcript 已写入: {out}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
