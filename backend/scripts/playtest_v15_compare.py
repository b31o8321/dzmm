"""Multi-model v0.15.2 playtest comparison.

Drives the same 6-turn scripted scenario against multiple models
(local Ollama qwen2.5:7b + 智谱 GLM via OpenAI-compatible API) and
reports per-model:
- v0.15 tag usage rate (the critical metric)
- legacy tag usage
- token consumption
- narrative character count
- NPC tracking accuracy
- per-turn breakdown

Uses DB ModelConfig records with api_key_ref pointing to OS keychain
(via dzmm.secrets) — same flow as the wizard. First-run bootstrap:

    cd backend && python scripts/playtest_v15_compare.py --store-zhipu-key <key>

Subsequent runs read from keychain:

    cd backend && python scripts/playtest_v15_compare.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import traceback
from collections import Counter
from pathlib import Path

# Resolve real $HOME BEFORE we override HOME (we use a temp HOME so DB
# writes don't pollute ~/.dzmm). The key store lives under the REAL home
# so subsequent script runs find it.
_real_home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
_KEY_STORE = _real_home / ".dzmm" / "playtest_keys.json"

_tmp = tempfile.mkdtemp(prefix="dzmm-compare-")
os.environ["HOME"] = _tmp

from sqlalchemy import select

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    Character, CharState, ModelConfig, NPC, Session as GameSession, World,
)
from dzmm.engine.genre_templates import apply_genre_template
from dzmm.models.client import GenerationParams, Message, ModelClient
from dzmm.models.ollama import OllamaClient
from dzmm.models.openai_compat import OpenAICompatClient
from dzmm.parsing.events import NarrativeDelta, TagComplete, UsageSummary
from dzmm.service.game import run_turn


ZHIPU_KEY_REF = "playtest_zhipu"


def _load_keystore() -> dict:
    if _KEY_STORE.exists():
        try:
            return json.loads(_KEY_STORE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def _save_keystore(d: dict) -> None:
    _KEY_STORE.parent.mkdir(parents=True, exist_ok=True)
    _KEY_STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    os.chmod(_KEY_STORE, 0o600)


def _mask(k: str) -> str:
    if not k:
        return ""
    return k[:4] + "…" + k[-4:] if len(k) > 8 else "…"


def maybe_store_key_and_exit():
    """If invoked with --store-zhipu-key <KEY>, persist to local store and exit."""
    if len(sys.argv) >= 3 and sys.argv[1] == "--store-zhipu-key":
        key = sys.argv[2].strip()
        if not key:
            print("ERROR: empty key", file=sys.stderr)
            sys.exit(1)
        store = _load_keystore()
        store[ZHIPU_KEY_REF] = key
        _save_keystore(store)
        print(f"✅ 智谱 API key stored at {_KEY_STORE} (ref={ZHIPU_KEY_REF}) [{_mask(key)}]")
        sys.exit(0)


# ──────────────────────────────────────────────────────────────
# Test scenario — same 6 actions across all models
# ──────────────────────────────────────────────────────────────

ACTIONS = [
    "环顾四周，先看清楚我现在在哪里。",
    "走到酒吧门口，仔细观察周围有什么可疑的人。",
    "走进酒吧，找一个看起来眼线多的人搭话，问问最近码头的怪事。",
    "请那个酒鬼喝一杯，套出他知道的事。",
    "顺着他指的方向，去雨夜码头查看尸体。",
    "我蹲下检查尸体身上的口袋和伤口。",
]

V15_TAGS = {"dice_request", "skill_request", "item_use", "attack",
            "initiative_request"}


async def seed_session(db, model_cfg: ModelConfig) -> tuple[GameSession, Character]:
    """Create a fresh world/character/session pinned to the given model config."""
    world = World(
        name="阴影城",
        content_md="""# 阴影城
永远笼罩浓雾的港口城市，雨水滴答个不停。

# 关键地点
- 警察局：堕落官僚
- 红灯区"潮湿酒吧"
- 雨夜码头：常有尸体浮出
- 旧公寓：侦探的栖身之所

# 当下危机
近一周码头出现 3 具相同伤口的无名尸体，警察压案。
""",
        style="noir",
    )
    db.add(world)
    await db.flush()

    template = apply_genre_template("悬疑探案")
    sb = template["stat_block"]

    char = Character(
        world_id=world.id,
        name="陈墨衍",
        profile_md="前警员，倔强、香烟不离手。",
        gender="male",
        base_stats_json="{}",
        strength=sb["strength"], dexterity=sb["dexterity"],
        constitution=sb["constitution"], intelligence=sb["intelligence"],
        wisdom=sb["wisdom"], charisma=sb["charisma"],
        max_hp=sb["max_hp"], max_sanity=sb["max_sanity"],
        max_stamina=sb["max_stamina"],
        skills_json=json.dumps(template["skills"]),
        inventory_json=json.dumps(template["inventory"]),
        equipment_json=json.dumps({}),
    )
    db.add(char)
    db.add(model_cfg)
    await db.flush()

    sess = GameSession(
        name="雨夜的尸体",
        world_id=world.id, character_id=char.id,
        gm_model_config_id=model_cfg.id,
        summarizer_model_config_id=model_cfg.id,
        settings_json=json.dumps({"debug_mode": True, "use_v10": False}),
    )
    db.add(sess)
    await db.flush()

    cs = CharState(session_id=sess.id,
                   stats_json=json.dumps({"hp": sb["max_hp"], "sanity": sb["max_sanity"]}),
                   stamina=sb["max_stamina"])
    db.add(cs)
    await db.commit()
    return sess, char


async def run_one_turn(db, sess_id: int, action: str, client) -> dict:
    narrative, tags, usage, err = [], [], None, None
    try:
        async for ev in run_turn(
            session=db, session_id=sess_id, user_action=action,
            client=client,
            params=GenerationParams(temperature=0.7, max_tokens=600),
        ):
            if isinstance(ev, NarrativeDelta):
                narrative.append(ev.text)
            elif isinstance(ev, TagComplete):
                tags.append((ev.name, dict(ev.attrs or {})))
            elif isinstance(ev, UsageSummary):
                usage = (ev.tokens_in, ev.tokens_out)
        await db.commit()
    except Exception as e:
        err = f"{e}\n{traceback.format_exc()[:500]}"
        await db.rollback()
    return {"narrative": "".join(narrative), "tags": tags,
            "usage": usage, "error": err}


async def playtest_one_model(
    model_label: str,
    client_factory,
    cfg_factory,
    output_lines: list[str],
) -> dict:
    """Run the 6-turn scenario against one model. Returns aggregate stats."""
    out = lambda s: (output_lines.append(s), print(s, flush=True))

    db_path = Path(_tmp) / f"{model_label}.db"
    engine = get_engine(f"sqlite+aiosqlite:///{db_path}")
    await init_db(engine)
    SM = async_session(engine)

    aggr = {
        "model": model_label,
        "tokens_in_total": 0,
        "tokens_out_total": 0,
        "narrative_chars_total": 0,
        "v15_tag_counts": Counter(),
        "legacy_tag_counts": Counter(),
        "errors": [],
        "turns_completed": 0,
        "final_npc_count": 0,
        "final_hp_change": 0,
    }

    out(f"\n{'═' * 76}")
    out(f"  🤖 模型: {model_label}")
    out(f"{'═' * 76}")

    try:
        async with SM() as db:
            cfg = cfg_factory()
            sess, char = await seed_session(db, cfg)
            client = client_factory()
            initial_hp = json.loads(
                (await db.execute(
                    select(CharState).where(CharState.session_id == sess.id)
                )).scalar_one().stats_json
            ).get("hp")

            for i, action in enumerate(ACTIONS, 1):
                out(f"\n──[回合 {i}]── PC: {action}")
                r = await run_one_turn(db, sess.id, action, client)
                if r["error"]:
                    out(f"  ❌ {r['error'][:200]}")
                    aggr["errors"].append((i, r["error"][:200]))
                    break
                aggr["turns_completed"] = i

                narr = r["narrative"].strip()
                aggr["narrative_chars_total"] += len(narr)
                out(f"  📖 ({len(narr)} chars) {narr[:200]}…" if len(narr) > 200 else f"  📖 {narr}")

                tags = r["tags"]
                tagcounts = Counter(t[0] for t in tags)
                for tn, _ in tags:
                    if tn in V15_TAGS:
                        aggr["v15_tag_counts"][tn] += 1
                    elif tn != "narrative":
                        aggr["legacy_tag_counts"][tn] += 1
                out(f"  🏷️  {dict(tagcounts)}")

                if r["usage"]:
                    aggr["tokens_in_total"] += r["usage"][0]
                    aggr["tokens_out_total"] += r["usage"][1]
                    out(f"  📊 ↑{r['usage'][0]} ↓{r['usage'][1]}")

            # Final state
            npcs = (await db.execute(
                select(NPC).where(NPC.session_id == sess.id))).scalars().all()
            aggr["final_npc_count"] = len(npcs)
            cs = (await db.execute(
                select(CharState).where(CharState.session_id == sess.id))).scalar_one()
            final_hp = json.loads(cs.stats_json).get("hp")
            aggr["final_hp_change"] = (final_hp or 0) - (initial_hp or 0)

    except Exception as e:
        out(f"\n  💥 SETUP FAIL: {e}\n{traceback.format_exc()[:500]}")
        aggr["errors"].append((0, str(e)[:200]))
    finally:
        await engine.dispose()

    return aggr


def print_comparison(results: list[dict], out_lines: list[str]) -> None:
    out = lambda s: (out_lines.append(s), print(s, flush=True))

    out(f"\n\n{'═' * 76}")
    out(f"  📊 多模型对比")
    out(f"{'═' * 76}\n")

    rows = []
    for r in results:
        v15 = sum(r["v15_tag_counts"].values())
        legacy = sum(r["legacy_tag_counts"].values())
        total_mech = v15 + legacy
        v15_pct = (v15 / total_mech * 100) if total_mech else 0
        rows.append({
            "model": r["model"],
            "turns": r["turns_completed"],
            "v15": v15,
            "legacy": legacy,
            "v15_pct": v15_pct,
            "tok_in": r["tokens_in_total"],
            "tok_out": r["tokens_out_total"],
            "narr": r["narrative_chars_total"],
            "npcs": r["final_npc_count"],
            "errors": len(r["errors"]),
        })

    out(f"  {'模型':<18} {'完成':<5} {'v15':<5} {'old':<5} {'v15%':<7} "
        f"{'tok↑':<8} {'tok↓':<7} {'字数':<6} {'NPCs':<5} {'err':<4}")
    out(f"  {'─' * 72}")
    for r in rows:
        out(f"  {r['model']:<18} {r['turns']:<5} {r['v15']:<5} {r['legacy']:<5} "
            f"{r['v15_pct']:<7.1f} {r['tok_in']:<8} {r['tok_out']:<7} "
            f"{r['narr']:<6} {r['npcs']:<5} {r['errors']:<4}")

    out(f"\n  v15 标签构成（按模型）:")
    for r in results:
        v15_d = dict(r["v15_tag_counts"])
        legacy_d = dict(r["legacy_tag_counts"])
        out(f"    {r['model']}:")
        out(f"      v15: {v15_d}")
        out(f"      legacy: {legacy_d}")


async def main():
    output_lines: list[str] = []
    results = []

    # Model registry
    model_specs = []

    # qwen2.5:7b via Ollama (always available)
    model_specs.append((
        "qwen2.5:7b",
        lambda: OllamaClient(
            name="qwen2.5:7b",
            base_url="http://localhost:11434",
            model="qwen2.5:7b",
            timeout=600.0,
        ),
        lambda: ModelConfig(
            name="qwen2.5:7b", type="ollama",
            base_url="http://localhost:11434",
            model_name="qwen2.5:7b", timeout=120.0,
        ),
    ))

    # 智谱 GLM models — read API key from local store (~/.dzmm/playtest_keys.json
    # written via --store-zhipu-key). DB ModelConfig.api_key_ref points at the
    # store key name; the client itself receives the resolved key.
    zhipu_key = _load_keystore().get(ZHIPU_KEY_REF, "").strip()
    if zhipu_key:
        zhipu_base = "https://open.bigmodel.cn/api/paas/v4"
        for glm_model in ["glm-4.5-air", "glm-4.6"]:
            model_specs.append((
                glm_model,
                lambda m=glm_model, k=zhipu_key: OpenAICompatClient(
                    name=m, base_url=zhipu_base,
                    api_key=k, model=m, timeout=300.0,
                ),
                lambda m=glm_model: ModelConfig(
                    name=m, type="openai_compat",
                    base_url=zhipu_base, model_name=m,
                    api_key_ref=ZHIPU_KEY_REF,
                    timeout=300.0,
                ),
            ))
    else:
        print(f"⚠️ 智谱 API key 未在 keychain ref={ZHIPU_KEY_REF}；"
              f"先跑 `python scripts/playtest_v15_compare.py --store-zhipu-key <key>` "
              f"再正常调用，本次跳过 GLM 对比。", file=sys.stderr)

    # Warm up each model so cold start doesn't blow first turn
    print(f"\n准备 {len(model_specs)} 个模型: {[s[0] for s in model_specs]}")

    for label, client_fac, cfg_fac in model_specs:
        try:
            print(f"⏳ 预热 {label}…", flush=True)
            cl = client_fac()
            async for _ in cl.stream(
                [Message(role="user", content="hi")],
                GenerationParams(temperature=0.1, max_tokens=4),
            ):
                pass
            print(f"  ✅ 预热完成", flush=True)
        except Exception as e:
            print(f"  ⚠️ 预热失败 {label}: {e}", flush=True)
            continue

        aggr = await playtest_one_model(label, client_fac, cfg_fac, output_lines)
        results.append(aggr)

    print_comparison(results, output_lines)

    # Save transcript
    out_path = Path(_tmp) / "comparison.txt"
    out_path.write_text("\n".join(output_lines), encoding="utf-8")
    print(f"\n📝 完整对比记录: {out_path}")


if __name__ == "__main__":
    maybe_store_key_and_exit()
    asyncio.run(main())
