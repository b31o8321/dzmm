"""Run an isolated open-world maturity playtest and emit a JSON report.

The script never reads or writes ``~/.dzmm``. It creates a dedicated HOME,
database, activity log, and report under ``--data-dir``.

Example:
    PYTHONPATH="$PWD/src" python scripts/playtest_v16_maturity.py --turns 50
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=50)
    parser.add_argument("--model", default="qwen2.5:7b-32k")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--provider", choices=("ollama", "lm_studio"), default="ollama")
    parser.add_argument("--num-ctx", type=int, default=16384)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--single-agent", action="store_true")
    return parser.parse_args()


ARGS = _parse_args()
DATA_DIR = (ARGS.data_dir or Path(tempfile.mkdtemp(prefix="dzmm-v016-maturity-"))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ["HOME"] = str(DATA_DIR)

# Imports that depend on dzmm.config must happen after HOME is isolated.
from sqlalchemy import func, select  # noqa: E402

from dzmm.api.routes_sessions.base import _initialize_framework_runtime  # noqa: E402
from dzmm.db.base import async_session, get_engine, init_db  # noqa: E402
from dzmm.db.models import (  # noqa: E402
    AgentMessage,
    AgentStream,
    Character,
    CharState,
    Location,
    Message as MessageRow,
    ModelConfig,
    Screenplay,
    Session as GameSession,
    SessionCampaignState,
    SessionEventState,
    StorySummary,
    World,
    WorldLocation,
)
from dzmm.models.client import GenerationParams, Message  # noqa: E402
from dzmm.models.ollama import OllamaClient  # noqa: E402
from dzmm.models.openai_compat import OpenAICompatClient  # noqa: E402
from dzmm.parsing.events import NarrativeDelta, UsageSummary  # noqa: E402
from dzmm.service.activity_log import read_recent  # noqa: E402
from dzmm.service.agents.streams import compress_if_needed  # noqa: E402
from dzmm.service.game import run_turn  # noqa: E402
from dzmm.service.summarizer import maybe_summarize  # noqa: E402
from dzmm.service.wizard_framework import finalize_framework  # noqa: E402


FRAMEWORK_PAYLOAD = {
    "name": "雾港档案",
    "genre": "悬疑惊悚",
    "style": "克制、写实、黑色电影",
    "description_md": (
        "海雾封锁了雾港。旧海关档案记载，失踪者都曾收到一枚无字铜票。"
        "巡夜署、潮汐商会与灯塔守望者围绕港口控制权彼此牵制。"
    ),
    "start_location_name": "旧海关站",
    "locations": [
        {
            "name": "旧海关站",
            "description_md": "停用的砖石海关站，地下档案库仍有电。",
            "location_type": "landmark",
            "initial_state": "normal",
            "connections": [
                {"target_name": "雾港码头", "direction": "east", "distance": 1, "travel_turns": 1},
                {"target_name": "潮汐市场", "direction": "south", "distance": 1, "travel_turns": 1},
            ],
        },
        {
            "name": "雾港码头",
            "description_md": "货仓与起重机隐入浓雾，夜间由巡夜署封锁。",
            "location_type": "city",
            "initial_state": "normal",
            "connections": [
                {"target_name": "旧海关站", "direction": "west", "distance": 1, "travel_turns": 1},
                {"target_name": "白塔灯塔", "direction": "north", "distance": 2, "travel_turns": 2},
            ],
        },
        {
            "name": "潮汐市场",
            "description_md": "白天售卖渔获，夜里交换消息与违禁品。",
            "location_type": "city",
            "initial_state": "normal",
            "connections": [
                {"target_name": "旧海关站", "direction": "north", "distance": 1, "travel_turns": 1},
                {"target_name": "白塔灯塔", "direction": "east", "distance": 2, "travel_turns": 2},
            ],
        },
        {
            "name": "白塔灯塔",
            "description_md": "仍在运转的老灯塔，地下机械室传出规律敲击声。",
            "location_type": "landmark",
            "initial_state": "normal",
            "connections": [
                {"target_name": "雾港码头", "direction": "south", "distance": 2, "travel_turns": 2},
                {"target_name": "潮汐市场", "direction": "west", "distance": 2, "travel_turns": 2},
            ],
        },
    ],
    "factions": [
        {
            "name": "巡夜署",
            "description_md": "名义上维护港区秩序，内部有人销毁失踪案卷。",
            "rival_faction_names": ["潮汐商会"],
            "ally_faction_names": [],
            "tension_rules": {"passive_gain_per_turn": 1, "threshold_conflict": 70},
        },
        {
            "name": "潮汐商会",
            "description_md": "控制码头货运的商人联盟，害怕旧账曝光。",
            "rival_faction_names": ["巡夜署"],
            "ally_faction_names": [],
            "tension_rules": {"passive_gain_per_turn": 1, "threshold_conflict": 75},
        },
    ],
    "npc_templates": [
        {
            "name": "韩策", "gender": "male", "role": "前档案员",
            "description_md": "谨慎寡言，熟悉旧海关站。", "motivation": "找回被删去的妹妹档案",
            "home_location_name": "旧海关站", "faction_name": "巡夜署",
            "contact_favor_threshold": 30, "contact_cooldown_turns": 8,
            "speech_pattern": "回答前总会先确认门是否关好。",
        },
        {
            "name": "苏芮", "gender": "female", "role": "市场情报贩子",
            "description_md": "消息灵通，不免费提供任何线索。", "motivation": "摆脱商会控制",
            "home_location_name": "潮汐市场", "faction_name": "潮汐商会",
            "contact_favor_threshold": 35, "contact_cooldown_turns": 8,
            "speech_pattern": "习惯把价码说成潮汐高度。",
        },
        {
            "name": "罗岑", "gender": "male", "role": "巡夜署队长",
            "description_md": "强硬守序，对封锁原因避而不谈。", "motivation": "阻止港口恐慌",
            "home_location_name": "雾港码头", "faction_name": "巡夜署",
            "contact_favor_threshold": 50, "contact_cooldown_turns": 10,
            "speech_pattern": "每句话都像在宣读条例。",
        },
        {
            "name": "闻笙", "gender": "female", "role": "灯塔守望者",
            "description_md": "独居白塔，记录每一次异常灯号。", "motivation": "查明海雾中的求救信号",
            "home_location_name": "白塔灯塔", "faction_name": "",
            "contact_favor_threshold": 25, "contact_cooldown_turns": 6,
            "speech_pattern": "用灯号节奏比喻人的情绪。",
        },
    ],
    "events": [
        {
            "name": "缺页档案", "summary_md": "旧海关站的失踪档案被人为撕去关键页。",
            "completion_criteria_md": "确认档案确系人为撕毁，并取得可核验编号或最后接触者证词。",
            "scope_type": "location", "scope_location_name": "旧海关站", "importance": 4,
            "trigger_conditions": {"type": "location_reached", "location_name": "旧海关站"},
            "is_repeatable": False, "cooldown_turns": 0,
        },
        {
            "name": "封锁线后的铜票", "summary_md": "码头封锁线后出现带盐霜的无字铜票。",
            "completion_criteria_md": "取得铜票实物或可验证记录，并确认它出现在封锁线后的运输路径。",
            "scope_type": "location", "scope_location_name": "雾港码头", "importance": 4,
            "trigger_conditions": {"type": "location_reached", "location_name": "雾港码头"},
            "is_repeatable": False, "cooldown_turns": 0,
        },
        {
            "name": "市场暗价", "summary_md": "苏芮掌握一份商会夜运清单。",
            "completion_criteria_md": "从苏芮处取得可核验的夜运清单内容。",
            "scope_type": "location", "scope_location_name": "潮汐市场", "importance": 3,
            "trigger_conditions": {"type": "location_reached", "location_name": "潮汐市场"},
            "is_repeatable": False, "cooldown_turns": 0,
        },
        {
            "name": "白塔求救灯", "summary_md": "白塔发出早已废止的海难求救灯号。",
            "completion_criteria_md": "取得闻笙的灯号记录并确认废止求救灯号确实出现。",
            "scope_type": "location", "scope_location_name": "白塔灯塔", "importance": 5,
            "trigger_conditions": {"type": "location_reached", "location_name": "白塔灯塔"},
            "is_repeatable": False, "cooldown_turns": 0,
        },
        {
            "name": "巡夜署内鬼", "summary_md": "销毁案卷的命令来自巡夜署内部。",
            "completion_criteria_md": "取得能指向巡夜署内部签发者的命令或证词。",
            "scope_type": "faction", "scope_faction_name": "巡夜署", "importance": 5,
            "trigger_conditions": {"type": "all", "children": []},
            "is_repeatable": False, "cooldown_turns": 0,
        },
        {
            "name": "雾中名单", "summary_md": "灯塔机械室藏着全部失踪者名单。",
            "completion_criteria_md": "找到并核验灯塔机械室中的失踪者名单。",
            "scope_type": "global", "importance": 5,
            "trigger_conditions": {"type": "all", "children": []},
            "is_repeatable": False, "cooldown_turns": 0,
        },
    ],
    "campaign": {
        "name": "无字铜票",
        "phases": [
            {
                "phase_id": 1, "name": "查档", "description": "确认失踪案被人为掩盖。",
                "prerequisite_phase_ids": [], "key_event_names": ["缺页档案", "封锁线后的铜票"],
                "required_count": 1,
            },
            {
                "phase_id": 2, "name": "追踪", "description": "沿夜运路线追查商会与巡夜署。",
                "prerequisite_phase_ids": [1], "key_event_names": ["市场暗价", "巡夜署内鬼"],
                "required_count": 1,
            },
            {
                "phase_id": 3, "name": "登塔", "description": "抵达白塔并揭开名单。",
                "prerequisite_phase_ids": [2], "key_event_names": ["白塔求救灯", "雾中名单"],
                "required_count": 1,
            },
        ],
    },
}


ACTIONS = [
    "我在旧海关站检查桌面与档案柜，只依据眼前事实行动。",
    "我请韩策说明被撕掉的档案页，并追问最后接触它的人。",
    "我搜索地下档案库并记录可验证编号与韩策证词；证据吻合后提交完成缺页档案调查。",
    "我前往雾港码头，在封锁线外观察巡逻规律。",
    "我和罗岑交谈，要求查看封锁令的签发记录。",
    "我检查码头与货仓，取得带盐霜铜票及运输记录后提交完成铜票调查。",
    "我前往潮汐市场寻找苏芮，只询问夜运清单。",
    "我用已经掌握的档案编号和苏芮交换可靠消息。",
    "我核对苏芮的夜运清单与巡夜署记录；内容可验证后提交完成市场暗价调查。",
    "我前往白塔灯塔，请闻笙展示异常灯号记录。",
    "我检查白塔机械室并核验闻笙的废止求救灯号记录，不凭空假定幕后人物。",
    "我把铜票、货单和灯号记录按时间排序；灯号证据吻合后提交完成白塔求救灯调查。",
]


async def _seed(sm) -> tuple[int, int]:
    async with sm() as s:
        framework_id = await finalize_framework(s, FRAMEWORK_PAYLOAD)
        world = World(
            name="雾港档案",
            content_md=FRAMEWORK_PAYLOAD["description_md"],
            style="dark",
            rules_json='{"mode":"standard"}',
        )
        character = Character(
            world=world,
            name="沈砚",
            gender="female",
            profile_md="前海事调查员，重视证据链，不接受未经证实的推断。",
            base_stats_json='{"hp":24,"sanity":36,"stamina":30}',
            max_hp=24,
            max_sanity=36,
            max_stamina=30,
            intelligence=15,
            wisdom=14,
            skills_json='{"调查":4,"察觉":3,"交涉":2}',
            inventory_json='[{"name":"记录本","qty":1},{"name":"手电筒","qty":1}]',
        )
        config = ModelConfig(
            name=f"maturity-{ARGS.model}",
            type=ARGS.provider,
            base_url=ARGS.base_url,
            model_name=ARGS.model,
            timeout=600.0,
        )
        s.add_all([world, character, config])
        await s.flush()
        session = GameSession(
            name="v0.16.0 独立 50 回合验收",
            world_id=world.id,
            character_id=character.id,
            framework_id=framework_id,
            gm_model_config_id=config.id,
            summarizer_model_config_id=config.id,
            settings_json=json.dumps({
                "use_v10": not ARGS.single_agent,
                "debug_mode": True,
            }),
        )
        s.add(session)
        await s.flush()
        s.add(CharState(
            session_id=session.id,
            stats_json=character.base_stats_json,
            stamina=character.max_stamina,
        ))
        await _initialize_framework_runtime(s, session, framework_id)
        await s.commit()
        return session.id, framework_id


async def _maintain_long_game(sm, session_id: int, client) -> None:
    async with sm() as s:
        await maybe_summarize(s, session_id, client)
        streams = (await s.execute(
            select(AgentStream).where(AgentStream.session_id == session_id)
        )).scalars().all()
        for stream in streams:
            if stream.kind == "scene":
                continue
            threshold = 30 if stream.kind == "gm_director" else 25
            keep = 10 if stream.kind == "gm_director" else 8
            await compress_if_needed(s, stream.id, client, threshold, keep)
        await s.commit()


async def _build_report(
    sm,
    session_id: int,
    framework_id: int,
    timings: list[float],
    gameplay_timings: list[float],
    maintenance_timings: list[float],
    first_narrative_timings: list[float],
) -> dict:
    records = read_recent(session_id=session_id, limit=5000)
    director = [r for r in records if r.get("kind") == "director_structure_quality"]
    turn_quality = [r for r in records if r.get("kind") == "turn_structure_quality"]
    proposed = sum(int(r.get("proposed_tags", 0)) for r in turn_quality)
    accepted = sum(int(r.get("accepted_tags", 0)) for r in turn_quality)
    rejected = sum(int(r.get("rejected_tags", 0)) for r in turn_quality)

    async with sm() as s:
        session = await s.get(GameSession, session_id)
        messages = (await s.execute(
            select(MessageRow).where(MessageRow.session_id == session_id)
        )).scalars().all()
        framework_locations = (await s.execute(
            select(WorldLocation).where(WorldLocation.framework_id == framework_id)
        )).scalars().all()
        runtime_locations = (await s.execute(
            select(Location).where(Location.session_id == session_id)
        )).scalars().all()
        event_states = (await s.execute(
            select(SessionEventState).where(SessionEventState.session_id == session_id)
        )).scalars().all()
        campaign_state = await s.get(SessionCampaignState, session_id)
        summary = (await s.execute(
            select(StorySummary).where(StorySummary.session_id == session_id)
        )).scalar_one_or_none()
        streams = (await s.execute(
            select(AgentStream).where(AgentStream.session_id == session_id)
        )).scalars().all()
        stream_counts = {}
        summary_counts = {}
        for stream in streams:
            stream_counts[f"{stream.kind}:{stream.ref}"] = (await s.execute(
                select(func.count(AgentMessage.id)).where(AgentMessage.stream_id == stream.id)
            )).scalar_one()
            summary_counts[f"{stream.kind}:{stream.ref}"] = (await s.execute(
                select(func.count(AgentMessage.id)).where(
                    AgentMessage.stream_id == stream.id,
                    AgentMessage.is_summary,
                )
            )).scalar_one()
        screenplay_count = (await s.execute(
            select(func.count(Screenplay.id)).where(Screenplay.session_id == session_id)
        )).scalar_one()

    diagnostics = []
    for message in messages:
        if message.role == "assistant":
            diagnostics.extend(json.loads(message.diagnostics_json or "[]"))

    framework_names = {row.name for row in framework_locations}
    runtime_names = {row.name for row in runtime_locations}
    placeholders = {"具体地点名", "地点名", "新地点", "目标地点", "A", "B", "…", "一句话"}
    invalid_event_statuses = sorted({
        row.status for row in event_states if row.status not in {"pending", "triggered", "completed"}
    })
    settings = json.loads(session.settings_json or "{}")
    pc_location_id = settings.get("pc_location_id")
    known_location_ids = {row.id for row in framework_locations}
    structured_count = sum(1 for row in director if row.get("structured") is True)

    return {
        "version": "0.16.0",
        "model": ARGS.model,
        "provider": ARGS.provider,
        "base_url": ARGS.base_url,
        "num_ctx": ARGS.num_ctx,
        "use_v10": not ARGS.single_agent,
        "data_dir": str(DATA_DIR),
        "session_id": session_id,
        "turns_requested": ARGS.turns,
        "turns_completed": session.turn_count,
        "message_count": len(messages),
        "director_quality_samples": len(director),
        "director_structured_count": structured_count,
        "director_structured_rate": structured_count / len(director) if director else 0.0,
        "proposed_tags": proposed,
        "accepted_tags": accepted,
        "rejected_tags": rejected,
        "tag_application_rate": accepted / proposed if proposed else 1.0,
        "diagnostic_count": len(diagnostics),
        "diagnostics": diagnostics,
        "illegal_runtime_locations": sorted(runtime_names - framework_names),
        "placeholder_runtime_locations": sorted(runtime_names & placeholders),
        "invalid_event_statuses": invalid_event_statuses,
        "pc_location_is_valid": pc_location_id in known_location_ids,
        "screenplay_count": screenplay_count,
        "campaign_phase": campaign_state.current_phase_id if campaign_state else None,
        "event_statuses": {row.event_id: row.status for row in event_states},
        "story_summary_present": bool(summary and summary.summary_text.strip()),
        "story_summary_chars": len(summary.summary_text) if summary else 0,
        "agent_message_counts": stream_counts,
        "agent_summary_counts": summary_counts,
        "turn_latency_seconds": {
            "avg": sum(timings) / len(timings) if timings else 0.0,
            "max": max(timings, default=0.0),
            "min": min(timings, default=0.0),
        },
        "gameplay_latency_seconds": {
            "avg": sum(gameplay_timings) / len(gameplay_timings) if gameplay_timings else 0.0,
            "max": max(gameplay_timings, default=0.0),
        },
        "maintenance_latency_seconds": {
            "avg": sum(maintenance_timings) / len(maintenance_timings)
            if maintenance_timings else 0.0,
            "max": max(maintenance_timings, default=0.0),
        },
        "first_narrative_latency_seconds": {
            "avg": sum(first_narrative_timings) / len(first_narrative_timings)
            if first_narrative_timings else 0.0,
            "max": max(first_narrative_timings, default=0.0),
        },
    }


async def main() -> None:
    db_path = DATA_DIR / "maturity.db"
    engine = get_engine(f"sqlite+aiosqlite:///{db_path}")
    await init_db(engine)
    sm = async_session(engine)
    if ARGS.provider == "ollama":
        client = OllamaClient(
            name=ARGS.model,
            base_url=ARGS.base_url,
            model=ARGS.model,
            timeout=600.0,
        )
        client.num_ctx = ARGS.num_ctx
    else:
        client = OpenAICompatClient(
            name=ARGS.model,
            base_url=ARGS.base_url,
            api_key="",
            model=ARGS.model,
            timeout=600.0,
        )

    ok, info = await client.health_check()
    if not ok:
        raise RuntimeError(f"model health check failed: {info}")
    print(f"model ready: {ARGS.model}", flush=True)
    async for _ in client.stream(
        [Message(role="user", content="只回复：好")],
        GenerationParams(temperature=0.1, max_tokens=4),
    ):
        pass

    session_id, framework_id = await _seed(sm)
    timings: list[float] = []
    gameplay_timings: list[float] = []
    maintenance_timings: list[float] = []
    first_narrative_timings: list[float] = []
    try:
        for turn in range(1, ARGS.turns + 1):
            action = ACTIONS[(turn - 1) % len(ACTIONS)]
            started = time.monotonic()
            narrative_chars = 0
            tokens = (0, 0)
            first_narrative_at: float | None = None
            async with sm() as s:
                try:
                    async for event in run_turn(
                        s,
                        session_id,
                        action,
                        client,
                        params=GenerationParams(temperature=0.55, max_tokens=700),
                        session_maker=sm,
                    ):
                        if isinstance(event, NarrativeDelta):
                            if first_narrative_at is None:
                                first_narrative_at = time.monotonic()
                            narrative_chars += len(event.text)
                        elif isinstance(event, UsageSummary):
                            tokens = (event.tokens_in, event.tokens_out)
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise
            gameplay_elapsed = time.monotonic() - started
            maintenance_started = time.monotonic()
            await _maintain_long_game(sm, session_id, client)
            maintenance_elapsed = time.monotonic() - maintenance_started
            elapsed = time.monotonic() - started
            timings.append(elapsed)
            gameplay_timings.append(gameplay_elapsed)
            maintenance_timings.append(maintenance_elapsed)
            first_narrative_timings.append(
                (first_narrative_at or time.monotonic()) - started
            )
            print(
                f"turn={turn:02d} seconds={elapsed:.2f} gameplay={gameplay_elapsed:.2f} "
                f"maintenance={maintenance_elapsed:.2f} narrative_chars={narrative_chars} "
                f"tokens_in={tokens[0]} tokens_out={tokens[1]}",
                flush=True,
            )

        report = await _build_report(
            sm, session_id, framework_id, timings,
            gameplay_timings, maintenance_timings, first_narrative_timings,
        )
        report_path = DATA_DIR / "maturity-report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        print(f"report={report_path}", flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
