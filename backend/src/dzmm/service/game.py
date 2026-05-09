# ============================================================
# 游戏核心服务（Service 层）
# ============================================================
# 【架构说明】
#   这是整个项目最核心的文件，run_turn() 是游戏引擎的"心脏"。
#   每回合的完整流程都在这里：
#     1. 读取数据库状态（世界/角色/NPC/剧本/摘要）
#     2. 组装 GM Prompt（system message）
#     3. 调用 LLM 流式生成
#     4. 边生成边解析 XML 标签（通过 StreamingTagParser）
#     5. 把解析事件 yield 给 API 层（SSE 推送给前端）
#     6. 解析完毕后执行 DB 副作用（apply_tags）
#     7. 持久化消息和状态
#
# 【关键 Python 概念：async generator】
#   run_turn() 是一个 async generator function（返回 AsyncIterator）。
#   它用 yield 逐条产出 ParseEvent，调用方（API 路由）用 async for 消费。
#   这样 LLM 还在生成时，前端就已经收到开头的文字，实现"打字机效果"。
#   【Java 对比】最接近的是 Reactor 的 Flux<ParseEvent> + emit()，
#   但 Python 的 async generator 语法更接近同步代码，不需要响应式编程知识。
# ============================================================

import json
import logging
import random
import re
from collections.abc import AsyncIterator
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Character,
    CharState,
    Faction,
    HiddenEvent,
    Location,
    LocationEdge,
    Message as MessageRow,
    NPC,
    NpcRelation,
    PCGoal,
    PlotThread,
    Screenplay,
    Session as GameSession,
    StorySummary,
    World,
)
from dzmm.models.client import GenerationParams, Message, ModelClient, TokenUsage
from dzmm.parsing.events import NarrativeDelta, ParseEvent, TagComplete, UsageSummary
from dzmm.parsing.stream_parser import StreamingTagParser
from dzmm.prompts.director_template import build_director_messages
from dzmm.prompts.gm_template import build_gm_messages
from dzmm.prompts.outliner_template import build_outliner_messages
from dzmm.prompts.polish_template import build_polish_messages
from dzmm.service.gm_graph import run_npc_post_pass, run_pre_pass
from dzmm.service.screenplay import get_active_screenplay
from dzmm.service.world_rag import get_world_md
from dzmm.service.activity_log import log_event
from dzmm.service.npc_initiative import find_initiative_npc
from dzmm.service.state_apply import apply_tags
from dzmm.service.state_apply.world_time import format_world_time_cn
from dzmm.service.state_apply.dice_monitor import (
    build_stuck_warning,
    detect_stuck_dice,
    extract_d20_values_from_messages,
)


log = logging.getLogger(__name__)

# 世界风格 → 剧本类型映射（用于生成剧本大纲时选择故事结构）
_STYLE_TO_GENRE: dict[str, str] = {
    "dark": "悬疑探案",
    "horror": "灾难求生",
    "healing": "恋爱攻略",
    "comedy": "英雄成长",
    "realistic": "英雄成长",
}
_DEFAULT_GENRE = "英雄成长"

# ── Prompt 上下文窗口大小 ──────────────────────────────────
# LLM 的 Context Window（上下文窗口）是有限的。
# 把所有历史消息都塞进 Prompt 会导致：
#   1. Token 超出限制被截断
#   2. 模型"迷失在长文本中"，开始重复 few-shot 示例（实测 70 回合后出现）
# 解决方案：只保留最近 N 条完整消息，更早的消息用"摘要"代替。
# N 随游戏进程自适应缩小：游戏越长，摘要质量越高，可以少要原文。
RECENT_WINDOW_DEFAULT = 12       # 0-30 回合
RECENT_WINDOW_LONG_GAME = 8      # 30-60 回合
RECENT_WINDOW_VERY_LONG = 6      # 60 回合以上

RECENT_WINDOW = RECENT_WINDOW_DEFAULT  # 向后兼容别名

# ── 场景节奏控制 ──────────────────────────────────────────
# 如果 PC 在同一地点停留太多回合（一直不推进剧情），
# GM Prompt 里会注入"场景压力"提示，强制推动故事发展。
SCENE_SOFT_PRESSURE_TURNS = 4   # 停留 4 回合：给 GM 提醒
SCENE_HARD_EXIT_TURNS = 7       # 停留 7 回合：强制推进（三个具体方案 + 禁令）


def _update_scene_turn_count(sess, completed_tags: list) -> None:
    """场景回合计数器更新：进入新地点时重置为 1，否则递增。

    any(条件 for x in 列表) → Python 的"短路求值生成器表达式"
    【Java 对比】相当于 list.stream().anyMatch(t -> t.name.equals("location_enter"))
    """
    location_entered = any(
        t.name == "location_enter" for t in completed_tags
    )
    if location_entered:
        sess.scene_turn_count = 1   # 进入新场景，重置计数
    else:
        sess.scene_turn_count = sess.scene_turn_count + 1


def _recent_window_for(turn_count: int) -> int:
    """根据当前回合数，返回应该保留多少条完整历史消息（自适应窗口）。"""
    if turn_count > 60:
        return RECENT_WINDOW_VERY_LONG
    if turn_count > 30:
        return RECENT_WINDOW_LONG_GAME
    return RECENT_WINDOW_DEFAULT


def _rough_token_count(messages: list[Message]) -> int:
    """Rough token estimate without spinning up tiktoken: roughly 1 token per
    1.5 CJK chars and 1 token per 4 ASCII chars. Used only for the long-context
    warning event in activity_log; precision is not required."""
    total = 0
    for m in messages:
        text = m.content or ""
        cjk = sum(1 for c in text if "一" <= c <= "鿿")
        ascii_count = len(text) - cjk
        total += int(cjk / 1.5) + int(ascii_count / 4)
    return total

_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks (DeepSeek-R1 / o1-style reasoning).
    Used in the no-tag fallback so the user sees a clean narrative."""
    return _THINK_RE.sub("", text)


def _assemble_full_output(events: list[ParseEvent]) -> str:
    """v0.10.4: 把 v0.10 多 Agent 流式产出的 ParseEvent 列表拼成一段
    coherent XML，存到 messages.content。

    关键：consecutive NarrativeDelta 合并成一个 <narrative>，而不是每个
    流式 delta 单独成 tag（那样会变成 <narrative>浓</narrative>
    <narrative>重</narrative>... 几十个碎标签）。"""
    parts: list[str] = []
    narrative_buf: list[str] = []

    def _flush_narrative() -> None:
        if narrative_buf:
            parts.append(f"<narrative>{''.join(narrative_buf)}</narrative>")
            narrative_buf.clear()

    for ev in events:
        if isinstance(ev, NarrativeDelta):
            narrative_buf.append(ev.text)
        elif isinstance(ev, TagComplete):
            _flush_narrative()
            parts.append(_serialize_event_for_history(ev))
    _flush_narrative()
    return "".join(parts)


def _serialize_event_for_history(ev: ParseEvent) -> str:
    """Reconstruct an XML-ish snippet from a ParseEvent so the messages
    table's `content` column captures what Scene + NPCs collectively
    produced this turn (used by recent_messages on later turns)."""
    if isinstance(ev, NarrativeDelta):
        return f"<narrative>{ev.text}</narrative>"
    if isinstance(ev, TagComplete):
        attrs = " ".join(f'{k}="{v}"' for k, v in (ev.attrs or {}).items())
        if ev.content:
            return (
                f"<{ev.name} {attrs}>{ev.content}</{ev.name}>"
                if attrs
                else f"<{ev.name}>{ev.content}</{ev.name}>"
            )
        return f"<{ev.name} {attrs}/>" if attrs else f"<{ev.name}/>"
    return ""


# PC name drift repair extracted to a sibling module (v0.1.6 refactor); the
# names are re-exported here so existing call-sites and tests still see them.
from dzmm.service.name_repair import (
    _NAME_PATTERNS,
    _SAY_BLOCK_RE,
    _repair_pc_name,
)


async def _auto_generate_screenplay(
    session: AsyncSession,
    sess: GameSession,
    world: World,
    char: Character,
    client: ModelClient,
) -> None:
    """Generate and persist a Screenplay outline on the first turn.

    Non-fatal: if LLM output can't be parsed as JSON, logs and returns.
    """
    genre = _STYLE_TO_GENRE.get(world.style or "", _DEFAULT_GENRE)
    char_name = char.name or "PC"

    msgs = build_outliner_messages(
        world_name=world.name or "",
        world_md=world.content_md or "",
        character_name=char_name,
        character_md=_format_character_card(char),
        genre=genre,
    )

    buf: list[str] = []
    async for chunk in client.stream(msgs, GenerationParams(max_tokens=2000, temperature=0.7)):
        if chunk.delta:
            buf.append(chunk.delta)

    raw = "".join(buf).strip()
    # Strip optional markdown code fences the model sometimes adds
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
    if raw.endswith("```"):
        raw = raw.rsplit("\n", 1)[0]

    data: dict | None = None
    # First try direct parse
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        pass

    # Fallback: regex-extract the outermost {...} block (handles leading/trailing text)
    if data is None:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
            except (ValueError, TypeError):
                pass

    if data is None:
        log.warning("auto_screenplay: JSON parse failed — using fallback skeleton")
        world_name = world.name or "未知世界"
        data = {
            "chapters": [
                {
                    "title": "第一章：开端",
                    "summary": f"PC 踏入{world_name}，遭遇初始冲突，卷入主线事件。",
                    "main_events": [
                        {
                            "description": "PC 与关键 NPC 相遇，接受主线任务",
                            "keywords": ["任务", "开始", "相遇"],
                            "criteria": "PC 明确了当前目标",
                        }
                    ],
                    "optional_events": [],
                    "main_npcs": [],
                },
                {
                    "title": "第二章：发展",
                    "summary": "主线矛盾激化，PC 面临关键抉择，迎来故事高潮。",
                    "main_events": [
                        {
                            "description": "核心矛盾爆发，PC 必须做出重大决定",
                            "keywords": ["冲突", "危机", "决断"],
                            "criteria": "PC 解决了核心冲突",
                        }
                    ],
                    "optional_events": [],
                    "main_npcs": [],
                },
            ],
            "main_characters": [],
            "ending": "PC 完成使命，故事在此画上句号。",
            "opening_hook": f"你站在{world_name}的某处，一段新的冒险即将开始……",
        }

    chapters = data.get("chapters", [])
    main_characters = data.get("main_characters", [])

    session.add(Screenplay(
        session_id=sess.id,
        world_id=world.id,
        version=1,
        genre=genre,
        chapters_json=json.dumps(chapters, ensure_ascii=False),
        main_characters_json=json.dumps(main_characters, ensure_ascii=False),
        ending_md=data.get("ending", ""),
        opening_hook=data.get("opening_hook", ""),
        current_chapter=1,
        completed_events_json="[]",
        status="active",
    ))
    await session.flush()
    log.info(
        "auto_screenplay: created for session %d (genre: %s, chapters: %d)",
        sess.id, genre, len(chapters),
    )


_XML_TAG_RE = re.compile(r"<(narrative|say|pc_action|state_change|location_enter)\b")

def _check_xml_drift(recent_messages: list) -> str:
    """Return a format reminder string if recent assistant messages lack XML tags.

    After summarization, the context loses XML-formatted examples.  When the
    LLM sees only plain-text assistant turns, it drifts to plain-text output.
    Detecting ≥2 consecutive plain-text assistant messages triggers a reminder
    injected into the current user action.
    """
    plain_count = 0
    for msg in reversed(recent_messages):
        if msg.role != "assistant":
            continue
        if _XML_TAG_RE.search(msg.content):
            break  # found a properly-formatted turn — no drift
        plain_count += 1
        if plain_count >= 2:
            return (
                "\n\n[GM 格式提醒] 请严格使用 XML 标签格式输出本回合内容："
                "旁白用 <narrative>…</narrative>，"
                "PC 行动用 <pc_action>…</pc_action>，"
                "NPC 对话用 <say speaker=\"NPC名\">…</say>。"
                "不要输出纯文本。"
            )
    return ""


async def run_turn(
    session: AsyncSession,
    session_id: int,
    user_action: str,
    client: ModelClient,
    params: GenerationParams | None = None,
    ollama_base_url: str | None = None,
    session_maker=None,
) -> AsyncIterator[ParseEvent]:
    """游戏引擎核心：处理一回合，流式产出解析事件。

    【函数类型：async generator】
      函数体内有 yield，所以这是一个 generator function。
      加上 async 就变成 async generator，返回 AsyncIterator[ParseEvent]。
      调用方用 async for ev in run_turn(...) 消费，每个 yield 暂停函数并把值传出去。
      与普通函数的区别：不是"执行完毕再返回"，而是"边执行边产出"。

    【调用方必须在 generator 耗尽后 commit DB session。】
    """
    # params=None 时使用默认参数（Python 惯用的"可选参数"写法）
    # 【Java 对比】相当于方法重载中的无参版本，或 Optional.orElse(new GenerationParams())
    params = params or GenerationParams()

    sess = await session.get(GameSession, session_id)
    if sess is None:
        raise ValueError(f"Session {session_id} not found")

    # v0.10.5: take state snapshot at turn START so delete_last_turn can
    # restore everything (stats / NPC favor / emotion / location / plot /
    # hidden events / factions / etc.).
    from dzmm.service.turn_snapshot import take_snapshot, serialize_snapshot
    snapshot_str = serialize_snapshot(await take_snapshot(session, session_id))

    world = await session.get(World, sess.world_id)
    char = await session.get(Character, sess.character_id)

    char_state = (
        await session.execute(
            select(CharState).where(CharState.session_id == session_id)
        )
    ).scalar_one_or_none()
    live_state = _build_live_state(char, char_state)

    summary_row = (
        await session.execute(
            select(StorySummary).where(StorySummary.session_id == session_id)
        )
    ).scalar_one_or_none()
    story_summary = summary_row.summary_text if summary_row else ""

    # v0.2.7 — auto-generate screenplay on first turn if none exists
    if sess.turn_count == 0:
        existing_sp = (await session.execute(
            select(Screenplay).where(
                Screenplay.session_id == session_id,
                Screenplay.status == "active",
            )
        )).scalar_one_or_none()
        if existing_sp is None:
            await _auto_generate_screenplay(session, sess, world, char, client)

    key_facts = await _build_key_facts(
        session, session_id, sess.turn_count, char,
        ollama_base_url=ollama_base_url,
        user_action=user_action,
    )

    settings = json.loads(sess.settings_json or "{}")

    # Multi-agent pre-pass: LangGraph StateGraph (rules + conditional dice enrichment).
    # Falls back to original key_facts on any error.
    if settings.get("use_graph"):
        key_facts = await run_pre_pass(key_facts, user_action, client)
    elif settings.get("director_pass"):
        # Legacy single-agent director pass (kept for backwards compatibility).
        try:
            dir_msgs = build_director_messages(key_facts, user_action)
            directive, _ = await client.complete(
                dir_msgs, GenerationParams(temperature=0.5, max_tokens=120)
            )
            if directive.strip():
                key_facts = key_facts + "\n\n## 🎬 导演预处理\n" + directive.strip()
        except Exception as exc:  # noqa: BLE001
            log.warning("director pass failed: %s", exc)

    # Doom meter: inject current pressure level + maybe trigger bad ending.
    doom = sess.doom_score
    if doom > 0:
        if doom < 60:
            doom_note = f"## ⚠️ 压力值（仅GM可见）\n当前厄运值：{doom}/100（低风险，正常叙事）。"
        elif doom < 80:
            doom_note = f"## ⚠️ 压力值（仅GM可见）\n当前厄运值：{doom}/100（中等压力）。叙事基调偏阴沉，NPC 更紧张，事态更难控制。"
            if random.random() < 0.10:
                doom_note += "\n\n🔴 **坏结局触发**：本回合必须演出一个不可逆的恶化事件并 emit `<ending type=\"bad\">`。"
        elif doom < 90:
            doom_note = f"## ⚠️ 压力值（仅GM可见）\n当前厄运值：{doom}/100（高压力）。世界对PC持续恶化。"
            if random.random() < 0.25:
                doom_note += "\n\n🔴 **坏结局触发**：本回合必须演出一个不可逆的恶化事件并 emit `<ending type=\"bad\">`。"
        elif doom < 100:
            doom_note = f"## ⚠️ 压力值（仅GM可见）\n当前厄运值：{doom}/100（临界崩溃）。"
            if random.random() < 0.50:
                doom_note += "\n\n🔴 **坏结局触发**：本回合必须演出一个不可逆的恶化事件并 emit `<ending type=\"bad\">`。"
        else:
            doom_note = f"## ⚠️ 压力值（仅GM可见）\n当前厄运值：100/100。\n\n🔴 **坏结局触发**：本回合必须演出末日事件并 emit `<ending type=\"bad\">`。"
        key_facts = key_facts + "\n\n" + doom_note

    # Critical-vitals hint: HP / sanity / stamina now clamp at 0 (see
    # state_apply.state_change._VITAL_STATS). When any hit 0 the panel was
    # showing a "down" PC but the GM kept narrating regular action — there
    # was no signal that the run should resolve. Inject a hard hint so the
    # GM either rescues (NPC saves PC, last-second救援) or emits an ending.
    crit_lines = []
    if (live_state.get("hp") or 0) <= 0:
        crit_lines.append("- HP=0：PC 已倒下 / 失去意识 / 濒死")
    if (live_state.get("sanity") or 0) <= 0:
        crit_lines.append("- sanity=0：PC 已陷入疯狂 / 精神崩溃")
    if crit_lines:
        key_facts = key_facts + (
            "\n\n## 💀 危急状态（仅GM可见）\n"
            + "\n".join(crit_lines)
            + "\n\n🔴 **必须立即解决**：本回合任选其一——\n"
              "  (a) 演出救援/治疗/缓解事件，让对应数值恢复至 ≥1（state_change 加正值）；\n"
              "  (b) 演出 PC 倒下的最终结局并 emit `<ending type=\"bad\">`。\n"
              "禁止当作没事继续推进剧情。"
        )

    # Content level injection — safe (default) uses no extra instruction.
    content_level = settings.get("content_level", "safe")
    if content_level == "mature":
        key_facts = key_facts + (
            "\n\n## 内容尺度\n"
            "本会话开启「成人向」模式：可包含暴力、酒精、亲密接触、负面情绪等成人主题，"
            "但避免直接的露骨色情或极端血腥；用文学化描写而非生理细节。"
        )
    elif content_level == "unrestricted":
        key_facts = key_facts + (
            "\n\n## 内容尺度\n"
            "本会话开启「无限制」模式：所有内容主题（含色情、极端暴力、心理黑暗）皆可出现，"
            "按剧情需要自然呈现，仍要服务故事而非纯刺激。"
        )

    recent = await _load_recent_messages(session, session_id, summary_row)

    # If the summarizer hasn't run yet (or failed) but the session is already
    # long, inject a recovery note so the GM doesn't "forget" the present.
    from dzmm.service.summarizer import SUMMARIZE_AFTER_TURNS
    if not story_summary and sess.turn_count > SUMMARIZE_AFTER_TURNS:
        key_facts = (
            "⚠️ 剧情摘要暂缺（摘要器尚未运行或失败）。"
            "请完全依赖下方的 recent messages 推断背景，"
            "保持当前场景的人物/地点/事件与消息历史一致，不要重置剧情或重新介绍已出现的 NPC。\n\n"
        ) + key_facts

    # XML format drift detection: if recent assistant messages lack <narrative>
    # tags (usually after summarization removes XML-formatted examples from
    # context), inject a compact reminder so the model realigns.
    xml_reminder = _check_xml_drift(recent)

    rules_mode = json.loads(world.rules_json or '{"mode":"light"}').get("mode", "light")

    character_md = _format_character_card(char)

    # v0.10 multi-agent runtime — toggle via settings.use_v10 (default ON).
    # When enabled, hand off the rest of the turn to the orchestrator: it runs
    # Director (sync if triggered), streams Scene, then fans out NPC actors.
    # The legacy single-agent path below acts as fallback (use_v10=False).
    if settings.get("use_v10", True):
        from dzmm.service.agents.orchestrator import run_turn_v10
        from dzmm.prompts.gm_template import _format_live_state

        live_state_text = _format_live_state(live_state)
        # v0.10.4 fix: assemble events into coherent text — consecutive
        # NarrativeDelta chunks become ONE <narrative>...</narrative> block
        # (was: each delta wrapped separately, producing fragmented output
        # like <narrative>浓</narrative><narrative>重</narrative>... in
        # messages.content).
        all_events: list[ParseEvent] = []
        completed_tags: list[TagComplete] = []
        narrative_parts: list[str] = []
        v10_usage = UsageSummary()

        async for ev in run_turn_v10(
            session,
            session_id=session_id,
            user_action=user_action,
            scene_client=client,
            director_client=client,
            npc_client=client,
            session_maker=session_maker,
            world_md=get_world_md(
                world.id,
                world.content_md or "",
                user_action,
                ollama_base_url,
            ),
            character_md=character_md,
            live_state_text=live_state_text,
            key_facts=key_facts,
            recent_messages=recent,
        ):
            if isinstance(ev, UsageSummary):
                v10_usage = ev
                continue  # don't forward to SSE
            all_events.append(ev)
            if isinstance(ev, TagComplete):
                completed_tags.append(ev)
            if isinstance(ev, NarrativeDelta):
                narrative_parts.append(ev.text)
            yield ev

        full_output = _assemble_full_output(all_events)
        next_turn = sess.turn_count + 1

        # Persist player's user message + aggregated assistant output into
        # the existing messages table. agent_streams already captured the
        # Director + per-NPC private histories during run_turn_v10.
        session.add(MessageRow(
            session_id=session_id, role="user",
            content=user_action, turn=next_turn,
        ))
        events_payload = [
            {
                "type": tag.name,
                "payload": dict(tag.attrs or {}),
                "content": tag.content or "",
            }
            for tag in completed_tags
        ]
        session.add(MessageRow(
            session_id=session_id, role="assistant",
            content=full_output, turn=next_turn,
            events_json=json.dumps(events_payload, ensure_ascii=False),
            snapshot_json=snapshot_str,
            tokens_in=v10_usage.tokens_in,
            tokens_out=v10_usage.tokens_out,
        ))
        await apply_tags(session, session_id, next_turn, completed_tags)
        # v0.10.5 — soft validation: warn if a brand-new NPC appeared
        # outside their primary_location with no encounter_setup. Soft
        # only — never aborts the SSE stream.
        from dzmm.service.encounter_check import check_encounter_warnings
        await check_encounter_warnings(
            session, session_id, completed_tags, current_turn=next_turn,
        )
        _update_scene_turn_count(sess, completed_tags)
        sess.turn_count = next_turn
        sess.last_played = datetime.now(UTC).replace(tzinfo=None)
        return  # short-circuit legacy path

    # ── Legacy single-agent path (kept as fallback / for use_v10=False) ──
    action_with_reminder = user_action
    if xml_reminder:
        action_with_reminder = user_action + "\n\n" + xml_reminder
        log.info("injecting XML format reminder for session %d (drift detected)", session_id)

    # v0.9.1 token reduction: inject only the conditional tag docs that
    # could plausibly fire this turn. Saves ~600-1500 tokens / 普通回合.
    sp_active = await get_active_screenplay(session, session_id)
    has_screenplay = sp_active is not None
    has_factions = (
        await session.execute(
            select(Faction.id).where(Faction.session_id == session_id).limit(1)
        )
    ).scalar_one_or_none() is not None
    # Combat: any combat_start within the last 5 turns OR a combat_start
    # without a matching combat_end in events_json
    has_combat_recent = await _detect_combat_recent(session, session_id, sess.turn_count)

    msgs = build_gm_messages(
        world_md=get_world_md(
            world.id,
            world.content_md or "",
            user_action,
            ollama_base_url,
        ),
        character_md=character_md,
        live_state=live_state,
        rules_mode=rules_mode,
        style=world.style,
        story_summary=story_summary,
        key_facts=key_facts,
        recent_messages=recent,
        current_action=action_with_reminder,
        has_screenplay=has_screenplay,
        has_factions=has_factions,
        has_combat_recent=has_combat_recent,
    )

    _debug_prompt_json = ""
    if settings.get("debug_mode"):
        _debug_prompt_json = json.dumps(
            [{"role": m.role, "content": m.content} for m in msgs],
            ensure_ascii=False,
        )

    # v0.2.1 — long-context observability. Estimate prompt token cost and
    # emit a warning event when the total crosses ~12k (most local 7B models
    # start truncating recent context and reciting few-shot examples beyond
    # this size). Non-fatal — purely advisory for the activity log UI.
    prompt_tokens = _rough_token_count(msgs)
    log_event(session_id, "turn_prompt_size",
              tokens=prompt_tokens, msgs=len(msgs))
    if prompt_tokens > 12000:
        log_event(session_id, "turn_prompt_warning",
                  tokens=prompt_tokens,
                  msg="prompt > 12k tokens, model may struggle with long context")

    parser = StreamingTagParser()
    full_output_parts: list[str] = []
    completed_tags: list[TagComplete] = []
    narrative_parts: list[str] = []
    usage = TokenUsage()
    narrative_emitted = False

    async for chunk in client.stream(msgs, params):
        if chunk.delta:
            full_output_parts.append(chunk.delta)
            for ev in parser.feed(chunk.delta):
                if isinstance(ev, TagComplete):
                    completed_tags.append(ev)
                if isinstance(ev, NarrativeDelta):
                    narrative_emitted = True
                    narrative_parts.append(ev.text)
                yield ev
        if chunk.usage is not None:
            usage = chunk.usage

    for ev in parser.finish():
        if isinstance(ev, TagComplete):
            completed_tags.append(ev)
        if isinstance(ev, NarrativeDelta):
            narrative_emitted = True
            narrative_parts.append(ev.text)
        yield ev

    full_output = "".join(full_output_parts)

    if not narrative_emitted and full_output.strip():
        fallback = _strip_thinking_tags(full_output).strip()
        if fallback:
            narrative_parts.append(fallback)
            yield NarrativeDelta(fallback)

    # PC-name drift repair — fix self-intros that the GM mangled (e.g. PC is
    # "Riku" but turn 7's <pc_action> says "我叫林峰"). Streaming clients have
    # already seen the bad text; the fix lands on the persisted Message and on
    # the narrative_text passed to apply_tags so subsequent renders are clean.
    if char is not None and char.name:
        full_output, n_fixes = _repair_pc_name(full_output, char.name)
        if n_fixes > 0:
            log.info(
                "repaired %d PC name drift(s) in turn %d", n_fixes, sess.turn_count
            )
            # Also repair the captured narrative parts so apply_tags / NER
            # fallback see the corrected text.
            joined = "".join(narrative_parts)
            repaired_joined, _ = _repair_pc_name(joined, char.name)
            narrative_parts = [repaired_joined] if repaired_joined else []

    # Optional narrative polish pass: run a prose-improvement LLM call on the
    # collected narrative, then emit a `narrative_revised` tag so the frontend
    # can replace the streaming placeholder with the polished version.
    if settings.get("narrative_polish") and narrative_parts:
        raw_narrative = "".join(narrative_parts).strip()
        if raw_narrative:
            try:
                polish_msgs = build_polish_messages(raw_narrative)
                polished, _ = await client.complete(
                    polish_msgs, GenerationParams(temperature=0.4, max_tokens=800)
                )
                if polished.strip():
                    narrative_parts = [polished.strip()]
                    yield TagComplete(name="narrative_revised", content=polished.strip())
            except Exception as exc:  # noqa: BLE001
                log.warning("polish pass failed: %s", exc)

    # Multi-agent NPC post-pass: check if any recently-seen NPCs need additional reactions.
    if settings.get("use_graph") and narrative_parts:
        recent_npc_rows = (
            await session.execute(
                select(NPC)
                .where(
                    NPC.session_id == session_id,
                    NPC.last_seen_turn >= sess.turn_count - 2,
                )
                .order_by(NPC.last_seen_turn.desc())
                .limit(5)
            )
        ).scalars().all()
        if recent_npc_rows:
            narrative_so_far = "".join(narrative_parts)
            npc_extra_events = await run_npc_post_pass(
                narrative_so_far, list(recent_npc_rows), user_action, client
            )
            for ev in npc_extra_events:
                completed_tags.append(ev)
                yield ev

    next_turn = sess.turn_count + 1

    # v0.9 T6 — NPC long-term memory: record <say> lines asynchronously.
    # Build name→id map, then fire-and-forget one task per qualifying say tag.
    if ollama_base_url and completed_tags:
        from dzmm.service.npc_memory import record_memory as _record_npc_memory
        npc_rows_for_mem = (
            await session.execute(
                select(NPC).where(NPC.session_id == session_id)
            )
        ).scalars().all()
        name_to_npc_id: dict[str, int] = {
            n.name: n.id for n in npc_rows_for_mem if n.name and n.id
        }
        for _tag in completed_tags:
            if _tag.name == "say":
                _speaker = _tag.attrs.get("speaker", "") if _tag.attrs else ""
                _npc_id = name_to_npc_id.get(_speaker)
                _text = (_tag.content or "").strip()
                if _npc_id and 20 < len(_text) <= 300:
                    asyncio.create_task(
                        _record_npc_memory(_npc_id, next_turn, _text, ollama_base_url)
                    )

    session.add(MessageRow(
        session_id=session_id, role="user", content=user_action, turn=next_turn,
    ))

    # Capture this turn's non-narrative events (state_change / npc_update /
    # dice / plot_event / hidden_event / etc.) so the frontend can render them
    # as inline event chips and so the message history retains structured
    # state transitions for replay/export.
    events_payload = [
        {
            "type": tag.name,
            "payload": dict(tag.attrs or {}),
            "content": tag.content or "",
        }
        for tag in completed_tags
    ]

    session.add(MessageRow(
        session_id=session_id, role="assistant", content=full_output, turn=next_turn,
        tokens_in=usage.input_tokens, tokens_out=usage.output_tokens,
        events_json=json.dumps(events_payload, ensure_ascii=False),
        prompt_json=_debug_prompt_json,
        snapshot_json=snapshot_str,
    ))

    await apply_tags(
        session,
        session_id,
        next_turn,
        completed_tags,
    )

    # v0.10.5 — soft validation: warn if a brand-new NPC appeared outside
    # their primary_location with no encounter_setup. Never aborts.
    from dzmm.service.encounter_check import check_encounter_warnings
    await check_encounter_warnings(
        session, session_id, completed_tags, current_turn=next_turn,
    )

    _update_scene_turn_count(sess, completed_tags)

    sess.turn_count = next_turn
    sess.last_played = datetime.now(UTC).replace(tzinfo=None)

    # v0.2.7 — NPC initiative check. After this turn completes, find if any
    # NPC is eligible to proactively contact PC. If yes, yield a synthetic
    # npc_initiative tag event; frontend will auto-trigger a /npc_tick call.
    initiative_npc = await find_initiative_npc(session, session_id, next_turn)
    if initiative_npc is not None:
        initiative_npc.last_initiative_turn = next_turn
        yield TagComplete(
            name="npc_initiative",
            attrs={"npc": initiative_npc.name},
            content="",
        )
        log.info(
            "npc_initiative scheduled: %s (turn %d)", initiative_npc.name, next_turn
        )


def _extract_pc_hooks(profile_md: str) -> dict[str, list[str]]:
    """Heuristic extraction of abilities/items/weaknesses from profile_md.

    Looks for markdown headings, bold runs, or key:value lines whose key
    matches a known PC-hook category, then captures the trailing list items
    or comma-separated phrases until the next section break."""
    out: dict[str, list[str]] = {"abilities": [], "items": [], "weaknesses": []}
    if not profile_md:
        return out
    section_pat = {
        "abilities": r"(?:能力|技能|绝技|擅长|专精)",
        "items": r"(?:物品|装备|道具|随身|身上)",
        "weaknesses": r"(?:弱点|弱项|禁忌|忌讳|害怕|畏惧)",
    }
    for key, kw in section_pat.items():
        m = re.search(
            rf"(?:^#+\s*{kw}|\*\*\s*{kw}\s*\*\*|{kw}[:：])",
            profile_md,
            re.M,
        )
        if not m:
            continue
        rest = profile_md[m.end():]
        next_heading = re.search(
            r"^#+\s|\*\*\s*[一-鿿]{2,4}\s*\*\*", rest, re.M
        )
        block = rest[: next_heading.start()] if next_heading else rest
        items = re.findall(r"[-•*]\s*(.+?)(?:$|\n)", block)
        if not items:
            items = [
                s.strip()
                for s in re.split(r"[,，、；;]", block.strip())
                if s.strip()
            ][:6]
        out[key] = [it.strip()[:50] for it in items if it.strip()][:6]
    return out


_CHARACTER_MD_BUDGET = 1200  # chars; trim wizard-generated profiles past this


def _truncate_character_md(profile: str, budget: int = _CHARACTER_MD_BUDGET) -> str:
    """Trim long PC profiles down to a ~budget character cap by keeping the
    head (basic info + opening sections) and dropping later sections. Hooks
    (abilities / items / weaknesses) are already extracted into key_facts
    by _extract_pc_hooks, so trimming here doesn't lose the GM-actionable
    parts — it just drops the prose-heavy backstory tail.

    Strategy: if profile fits, return as-is; else cut at the last `\n## ` /
    `\n# ` heading boundary that fits within budget; if no such boundary,
    hard-cut at budget chars + ellipsis marker.
    """
    if len(profile) <= budget:
        return profile
    # Try to cut at a markdown section boundary
    head = profile[:budget]
    # Find last "\n## " or "\n# " inside head
    cut = max(head.rfind("\n## "), head.rfind("\n# "))
    if cut > budget // 2:  # only honor if reasonably far in
        return profile[:cut].rstrip() + "\n\n（…后续详细背景已省略，详细钩子见 key_facts）"
    return profile[:budget].rstrip() + "…\n\n（…profile 已截断，详细钩子见 key_facts）"


_GENDER_CN = {"male": "男", "female": "女"}


def _format_character_card(char: Character) -> str:
    """Prepend `等级: Lv N` and `性别: 男/女` so the GM has both progression
    and gender-aware context when narrating challenges, NPC reactions, and
    relational scenes. Long profiles are truncated (see _truncate_character_md)."""
    profile = (char.profile_md or "").strip()
    level_line = f"等级: Lv {char.level}"
    header_lines = [level_line]
    if (char.gender or "") in _GENDER_CN:
        header_lines.append(f"性别: {_GENDER_CN[char.gender]}")
    header = "\n".join(header_lines)
    if profile:
        profile = _truncate_character_md(profile)
        return f"{header}\n\n{profile}"
    return header


def _build_live_state(char: Character, cs: CharState | None) -> dict:
    if cs is None:
        return json.loads(char.base_stats_json or "{}")
    out = json.loads(cs.stats_json or "{}")
    out["inventory"] = json.loads(cs.inventory_json or "[]")
    return out


async def _load_recent_messages(
    session: AsyncSession,
    session_id: int,
    summary_row: StorySummary | None,
) -> list[Message]:
    sess = await session.get(GameSession, session_id)
    turn_count = sess.turn_count if sess is not None else 0
    window = _recent_window_for(turn_count)

    high_water = summary_row.last_summarized_msg_id if summary_row else 0
    rows = (
        await session.execute(
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .where(MessageRow.id > high_water)
            .order_by(MessageRow.id.desc())
            .limit(window)
        )
    ).scalars().all()
    rows = list(reversed(rows))
    return [Message(role=r.role, content=r.content) for r in rows]


# NPC dossier formatters extracted to a sibling module (v0.1.6 refactor); the
# names are re-exported here so existing call-sites and tests still see them.
from dzmm.service.npc_dossier import (
    _format_npc_dossier,
    _format_npc_short,
    _npc_revealed,
)


async def _detect_combat_recent(
    session: AsyncSession, session_id: int, current_turn: int
) -> bool:
    """True if any combat_start event happened in the last 5 turns AND no
    later combat_end has closed it. Used to decide whether to inject the
    combat tag docs into the GM prompt."""
    if current_turn < 1:
        return False
    rows = (await session.execute(
        select(MessageRow.events_json)
        .where(
            MessageRow.session_id == session_id,
            MessageRow.role == "assistant",
            MessageRow.turn >= max(1, current_turn - 5),
        )
        .order_by(MessageRow.turn.asc(), MessageRow.id.asc())
    )).scalars().all()
    open_combats = 0
    for raw in rows:
        if not raw:
            continue
        try:
            evs = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(evs, list):
            continue
        for ev in evs:
            if not isinstance(ev, dict):
                continue
            t = ev.get("type")
            if t == "combat_start":
                open_combats += 1
            elif t == "combat_end" and open_combats > 0:
                open_combats -= 1
    # Inject combat docs if there's an open combat OR a recent battle (whether closed)
    if open_combats > 0:
        return True
    # Closed combats in last 5 turns — still useful so GM can re-open if needed
    for raw in rows:
        if raw and "combat_start" in raw:
            return True
    return False


def _render_event(ev: "str | dict") -> str:
    """Render a screenplay event — new dict format or legacy string."""
    if isinstance(ev, str):
        return ev
    desc = ev.get("description", "")
    keywords = ev.get("keywords") or []
    criteria = ev.get("criteria", "")
    parts = [desc]
    if keywords:
        parts.append(f"  关键词：{'／'.join(str(k) for k in keywords)}")
    if criteria:
        parts.append(f"  完成标准：{criteria}")
    return "\n".join(parts)


async def _build_key_facts(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    character: Character | None = None,
    ollama_base_url: str | None = None,
    user_action: str = "",
) -> str:
    """Build NPC + plot context with a 3-pass union:
    1. Pinned NPCs (no limit) — full dossier
    2. Recently-seen NPCs (top 8 by last_seen_turn, excluding pinned) — short line
    3. Recalled NPCs — drained from Session.recall_pending_json — full dossier

    Also: pin the PC identity at the very top (anti-drift — fixes a v0.9 bug
    where the GM started referring to PC by a different name after ~3 turns)
    and append GM-only "暗中状态" (hidden events) at the bottom.
    """
    pinned_npcs = (
        await session.execute(
            select(NPC)
            .where(NPC.session_id == session_id, NPC.pinned == True)  # noqa: E712
            .order_by(NPC.last_seen_turn.desc())
        )
    ).scalars().all()
    pinned_ids = {n.id for n in pinned_npcs}

    recent_npcs = (
        await session.execute(
            select(NPC)
            .where(NPC.session_id == session_id)
            .order_by(NPC.last_seen_turn.desc())
            .limit(16)
        )
    ).scalars().all()
    recent_filtered: list[NPC] = []
    for n in recent_npcs:
        if n.id in pinned_ids:
            continue
        recent_filtered.append(n)
        if len(recent_filtered) >= 8:
            break

    sess = await session.get(GameSession, session_id)
    recalled_names: list[str] = []
    if sess is not None:
        try:
            raw = json.loads(sess.recall_pending_json or "[]")
            if isinstance(raw, list):
                recalled_names = [str(x) for x in raw if x]
        except (TypeError, ValueError):
            recalled_names = []
        # Drain — recall is one-shot.
        if recalled_names:
            sess.recall_pending_json = "[]"

    recalled_npcs: list[NPC] = []
    seen_ids = pinned_ids | {n.id for n in recent_filtered}
    for name in recalled_names:
        npc = (
            await session.execute(
                select(NPC).where(
                    NPC.session_id == session_id, NPC.name == name
                )
            )
        ).scalar_one_or_none()
        if npc is not None and npc.id not in seen_ids:
            recalled_npcs.append(npc)
            seen_ids.add(npc.id)

    threads = (
        await session.execute(
            select(PlotThread)
            .where(PlotThread.session_id == session_id, PlotThread.status == "active")
            .order_by(PlotThread.importance.desc(), PlotThread.id.desc())
            .limit(8)
        )
    ).scalars().all()

    # v0.2.5 — turn anchor at the head of key_facts so the GM doesn't drift on
    # which turn it is when summary windows compress earlier rounds.
    parts: list[str] = [f"**当前是第 {current_turn} 回合**"]

    # PC identity lock — top priority, prevents the GM drifting to a different
    # PC name after a few turns. character.name is the load-bearing field;
    # everything else is a hint.
    if character is not None:
        identity_lines = [
            "## PC 身份（最高优先级，永不可改）",
            f"姓名: {character.name}",
        ]
        profile = (character.profile_md or "").strip()
        if profile:
            # Keep it short — first 80 chars of the profile, single line.
            snippet = profile.replace("\n", " ").strip()[:80]
            if snippet:
                identity_lines.append(f"身份: {snippet}")
        identity_lines.append(
            "无论后文如何，PC 的姓名必须始终是上面这个，不得改名、不得替换、不得简称为别的名字。"
        )
        parts.append("\n".join(identity_lines))

    # v0.8 T11 — world time: inject current in-world day/period/weather so GM
    # knows when to advance time and can reference it in narrative.
    if sess is not None:
        wt_str = format_world_time_cn(sess.world_time_json)
        if wt_str:
            parts.append(f"\n## 当前时间\n{wt_str}")

    if pinned_npcs:
        parts.append("📌 重点 NPC（始终在场或玩家关注）：")
        for n in pinned_npcs:
            parts.append(_format_npc_dossier(n))

    # v0.9 T6 — NPC long-term memory: inject top-k recalled lines per pinned
    # NPC that match the current user action. Fire-and-forget on failure.
    if ollama_base_url and user_action and pinned_npcs:
        from dzmm.service.npc_memory import retrieve_memories as _retrieve_npc_memory
        for npc in list(pinned_npcs)[:4]:
            try:
                mems = await _retrieve_npc_memory(npc.id, user_action, ollama_base_url)
                if mems:
                    parts.append(
                        f"\n## {npc.name} 私人记忆（仅 GM 可见，NPC 行为应一致）"
                    )
                    for m in mems:
                        parts.append(f"- {m}")
            except Exception:  # noqa: BLE001
                pass

    if recent_filtered:
        parts.append("\nNPC 列表：" if not pinned_npcs else "\n最近出现的其他 NPC：")
        for n in recent_filtered:
            parts.append(_format_npc_short(n))

    if recalled_npcs:
        parts.append("\n🔁 本回合回归的 NPC（请重新带入设定）：")
        for n in recalled_npcs:
            parts.append(_format_npc_dossier(n))

    if threads:
        parts.append("\n进行中的剧情线：")
        for t in threads:
            stars = "★" * t.importance
            parts.append(f"- [{t.type} {stars}] {t.description}")

    active_goals = (
        await session.execute(
            select(PCGoal).where(
                PCGoal.session_id == session_id,
                PCGoal.status == "active",
            ).order_by(PCGoal.priority.desc(), PCGoal.id.desc()).limit(8)
        )
    ).scalars().all()

    if active_goals:
        parts.append("\nPC 当前目标：")
        for g in active_goals:
            prio_mark = {"high": "★★★", "normal": "★★", "low": "★"}.get(g.priority, "★★")
            parts.append(f"- [id={g.id}] {prio_mark} {g.description}")

    # v0.2.6 — current scene context (location + in-scene NPCs + items).
    current_loc = (
        await session.execute(
            select(Location).where(
                Location.session_id == session_id,
                Location.is_current == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if current_loc is None:
        # GM has been narrating without ever registering a location (real-
        # world session showed 17 turns with zero <location_enter>). Without
        # a location, the side panel's 当前场所 is empty and scene-budget
        # logic can't fire. Tell GM to register one this turn before doing
        # anything else.
        parts.append(
            "\n## ⚠️ 场所登记缺失（强制）\n"
            "本会话尚未登记任何地点，前端「当前场所」一直空白。**本回合 narrative "
            "开头必须 emit `<location_enter name=\"具体地点名\" description=\"一句话\"/>`** "
            "（如 「教堂地下室」 / 「九龙城寨夜市」）。已经在该地点的话也算"
            "首次登记，必须 emit。"
        )
    if current_loc is not None:
        loc_lines = [f"\n## 当前场地：{current_loc.name}"]
        if current_loc.description:
            loc_lines.append(f"描述：{current_loc.description}")

        # NPCs physically present in this location (from all three NPC lists)
        all_collected_npcs = list(pinned_npcs) + list(recent_filtered) + list(recalled_npcs)
        scene_npcs = [
            n for n in all_collected_npcs
            if (n.current_location or "").lower() == current_loc.name.lower()
        ]
        if scene_npcs:
            loc_lines.append("在场 NPC：" + "、".join(n.name for n in scene_npcs))
        else:
            loc_lines.append("在场 NPC：无")

        # Items in this location
        try:
            items = json.loads(current_loc.items_json or "[]")
            if not isinstance(items, list):
                items = []
        except (TypeError, ValueError):
            items = []
        if items:
            item_strs = []
            for i in items:
                item_name = i.get("name", "")
                if not item_name:
                    continue
                item_desc = i.get("description", "")
                item_strs.append(f"{item_name}（{item_desc}）" if item_desc else item_name)
            if item_strs:
                loc_lines.append("关键物品：" + "、".join(item_strs))

        loc_lines.append(
            "（NPC 离开此地时 emit `<npc_update name=\"X\" location=\"\"/>`；"
            "进入新地点时 emit `<npc_update name=\"X\" location=\"新地名\"/>`；"
            "引入新物品 emit `<location_item name=\"物品\" description=\"描述\" action=\"add\"/>`；"
            "物品被取走/消耗 emit `<location_item name=\"物品\" action=\"remove\"/>`）"
        )
        parts.append("\n".join(loc_lines))

        # v0.10 T12 — 周边拓扑：列出当前地点已确认的邻接关系，
        # 让 GM 把"PC 离开此处"这类决策约束在已知拓扑里，避免凭"地名相似"
        # 自己脑补关系造成的拓扑漂移。
        edges_out = (await session.execute(
            select(LocationEdge, Location)
            .join(Location, LocationEdge.to_loc_id == Location.id)
            .where(
                LocationEdge.session_id == session_id,
                LocationEdge.from_loc_id == current_loc.id,
            )
        )).all()
        edges_in = (await session.execute(
            select(LocationEdge, Location)
            .join(Location, LocationEdge.from_loc_id == Location.id)
            .where(
                LocationEdge.session_id == session_id,
                LocationEdge.to_loc_id == current_loc.id,
            )
        )).all()
        topo_lines: list[str] = []
        for e, peer in edges_out:
            topo_lines.append(
                f"- 此处 {e.relation} → {peer.name}"
                + (f"（{e.description}）" if e.description else "")
            )
        for e, peer in edges_in:
            topo_lines.append(
                f"- {peer.name} {e.relation} → 此处"
                + (f"（{e.description}）" if e.description else "")
            )
        if topo_lines:
            parts.append(
                "\n## 周边拓扑（已确认，禁止违背）\n" + "\n".join(topo_lines)
                + "\n（PC 离开此处只能去**与此处直接相连**的地点；"
                "进入新地点必须先 emit `<location_edge>` 把空间关系锁住。）"
            )

    # v0.10 T12 — drain topology warnings recorded by last turn's
    # _apply_location_enter. Surfaces "你上回合从 A 跳到 B 但没 emit edge"
    # so this turn's GM is forced to emit the missing relationship.
    if sess is not None:
        try:
            warnings = json.loads(sess.topology_warning_json or "[]")
            if not isinstance(warnings, list):
                warnings = []
        except (TypeError, ValueError):
            warnings = []
        if warnings:
            parts.append(
                "\n## ⚠️ 上一回合拓扑越界\n"
                + "\n".join(f"- {w}" for w in warnings)
            )
            sess.topology_warning_json = "[]"

    # v0.3.0 — Scene turn pressure. When the session has been at the same
    # location for many turns, inject an escalating directive to force scene
    # closure. Hard cap at SCENE_HARD_EXIT_TURNS prevents indefinite loops.
    if current_loc is not None and sess is not None:
        stc = sess.scene_turn_count or 0
        if stc >= SCENE_HARD_EXIT_TURNS:
            parts.append(
                f"\n## 🚨 场景强推（已在「{current_loc.name}」滞留 {stc} 回合）\n"
                "**本回合必须结束当前场景**，选择以下任一方式立即执行：\n"
                "(a) 用一个环境事件强制打断（有人闯入 / 危险爆发 / 时限耗尽），PC **必须** 离开；\n"
                "(b) 揭示足以让 PC 立刻行动的决定性信息，随后 emit "
                "`<location_enter name=\"新地点\" description=\"一句话\"/>` 推进；\n"
                "(c) NPC 明确宣告「此处已谈无可谈」，给出下一目的地。\n"
                "**禁止**：在此场景继续新增细节、旁支问题、模糊引导。\n"
                "强推要求立刻执行，不接受「下一回合」的推迟。"
            )
        elif stc >= SCENE_SOFT_PRESSURE_TURNS:
            parts.append(
                f"\n## ⏰ 场景时间提醒（已在「{current_loc.name}」{stc} 回合）\n"
                "本回合必须提供明确的场景推进路径之一：\n"
                "(a) 揭示让 PC 能够立刻行动的关键信息（名字/地点/方法）；\n"
                "(b) NPC 主动改变立场或给出具体让步；\n"
                "(c) 环境事件中断当前对话/探索节奏。\n"
                "禁止「碎片化喂养」——把本可一回合说清的内容再拆分。"
            )

    # PC mood — surfaced so GM tunes language to current emotional state.
    if sess is not None:
        try:
            moods = json.loads(sess.pc_mood_json or "{}")
        except (TypeError, ValueError):
            moods = {}
        if isinstance(moods, dict) and moods:
            sorted_moods = sorted(
                ((str(k), int(v)) for k, v in moods.items() if isinstance(v, (int, float))),
                key=lambda x: -x[1],
            )[:5]
            if sorted_moods:
                parts.append("\nPC 当前心情：")
                parts.append("- " + " / ".join(f"{k}({v})" for k, v in sorted_moods))

    # Active NPC↔NPC relations — keep recent 10 so worldbuilding stays consistent.
    relations = (
        await session.execute(
            select(NpcRelation)
            .where(NpcRelation.session_id == session_id)
            .order_by(NpcRelation.introduced_turn.desc(), NpcRelation.id.desc())
            .limit(10)
        )
    ).scalars().all()
    if relations:
        parts.append("\nNPC 关系：")
        for r in relations:
            parts.append(f"- {r.npc_a} ↔ {r.npc_b} [{r.kind}]")

    # v0.1.0 — Screenplay progress (active screenplay only). Placed before the
    # hidden_events block so the GM sees "what main events are still pending"
    # alongside "what hidden timers are running" — both are GM-only operational
    # state. Legacy sessions without a Screenplay row simply skip this block.
    sp = (
        await session.execute(
            select(Screenplay)
            .where(
                Screenplay.session_id == session_id,
                Screenplay.status == "active",
            )
            .order_by(Screenplay.version.desc())
        )
    ).scalars().first()
    if sp is not None:
        try:
            chapters = json.loads(sp.chapters_json or "[]")
        except (TypeError, ValueError):
            chapters = []
        if not isinstance(chapters, list):
            chapters = []
        try:
            completed = json.loads(sp.completed_events_json or "[]")
        except (TypeError, ValueError):
            completed = []
        if not isinstance(completed, list):
            completed = []
        try:
            main_chars = json.loads(sp.main_characters_json or "[]")
        except (TypeError, ValueError):
            main_chars = []
        if not isinstance(main_chars, list):
            main_chars = []

        if chapters:
            cur_idx = max(0, min(sp.current_chapter - 1, len(chapters) - 1))
            cur_ch = chapters[cur_idx] if isinstance(chapters[cur_idx], dict) else {}

            sp_lines: list[str] = [
                "\n## 当前剧本进度（GM 严格遵守主线，分支由 PC 探索触发）",
                f"当前章节：第 {sp.current_chapter} 章「{cur_ch.get('title', '')}」"
                f"（共 {len(chapters)} 章）",
            ]

            main_events = cur_ch.get("main_events") or []
            if isinstance(main_events, list) and main_events:
                sp_lines.append("本章主线（必须演完才能推进下章）：")
                for i, ev in enumerate(main_events):
                    done = any(
                        isinstance(c, dict)
                        and c.get("chapter") == sp.current_chapter
                        and c.get("event_idx") == i
                        and c.get("type") == "main"
                        for c in completed
                    )
                    flag = "[done]" if done else "[pending]"
                    sp_lines.append(f"- {flag} {_render_event(ev)}")

            optional_events = cur_ch.get("optional_events") or []
            if isinstance(optional_events, list) and optional_events:
                sp_lines.append("本章可选支线（PC 主动探索才触发，不强制）：")
                for i, ev in enumerate(optional_events):
                    done = any(
                        isinstance(c, dict)
                        and c.get("chapter") == sp.current_chapter
                        and c.get("event_idx") == i
                        and c.get("type") == "optional"
                        for c in completed
                    )
                    flag = "[done]" if done else "[optional]"
                    sp_lines.append(f"- {flag} {_render_event(ev)}")

            # Main NPCs whose intro_chapter is on or before current — surface
            # only the names; details should already exist in the NPC list above
            # once the GM declares them. Cap at 5 to keep the block compact.
            existing_names = {n.name for n in (pinned_npcs or [])} | {
                n.name for n in (recent_filtered or [])
            }
            pending_intro: list[str] = []
            for c in main_chars:
                if not isinstance(c, dict):
                    continue
                name = str(c.get("name") or "").strip()
                if not name or name in existing_names:
                    continue
                try:
                    intro_ch = int(c.get("intro_chapter", 1))
                except (TypeError, ValueError):
                    intro_ch = 1
                if intro_ch <= sp.current_chapter:
                    pending_intro.append(name)
            if pending_intro:
                names_str = " / ".join(pending_intro[:5])
                sp_lines.append(f"重要 NPC（应在不晚于本章出场）：{names_str}")

            ending_md = (sp.ending_md or "").strip()
            if ending_md:
                sp_lines.append(f"完结条件：{ending_md}")

            sp_lines.append(
                "（推进规则：主线 [pending] 事件每 1-2 回合至少演一个；"
                "支线 [optional] 等 PC 触发；演完后 emit "
                "<event_complete chapter=N event=M type=main/optional/>。"
                "本章主线全部 [done] 后 emit <chapter_advance/>。"
                "完结条件达成 emit <ending/>。"
                "重大决策（杀关键 NPC / 选阵营 / 放弃主线）"
                " emit <plot_turn impact=\"major\" description=\"...\"/>）"
            )
            parts.append("\n".join(sp_lines))

            # v0.2.2 P1.2 — 剧情强推:detect when the GM has gone several
            # turns without completing a main event in the current chapter
            # and inject a hard-priority directive naming the next pending
            # main event. Real play (72 turns stuck on chapter 1 of 3)
            # showed rule 24 alone wasn't enough; this section is read by
            # the GM each turn and effectively overrides the soft "1-2 回合"
            # rhythm with a concrete "演这一个，立刻 emit" instruction.
            if isinstance(main_events, list) and main_events:
                done_main_idxs = {
                    c.get("event_idx")
                    for c in completed
                    if isinstance(c, dict)
                    and c.get("chapter") == sp.current_chapter
                    and (c.get("type") or "main") == "main"
                    and isinstance(c.get("event_idx"), int)
                }
                pending_main_pairs = [
                    (i, ev) for i, ev in enumerate(main_events)
                    if i not in done_main_idxs
                ]
                if pending_main_pairs:
                    # Estimate how long ago we last completed a main event in
                    # this chapter. Prefer the recorded `turn` field on the
                    # most-recent completion; fall back to a coarse estimate
                    # for legacy rows that predate the turn field
                    # (current_turn - 3 * already-completed-main-count).
                    turns_recorded = [
                        c.get("turn")
                        for c in completed
                        if isinstance(c, dict)
                        and c.get("chapter") == sp.current_chapter
                        and (c.get("type") or "main") == "main"
                        and isinstance(c.get("turn"), int)
                    ]
                    if turns_recorded:
                        last_progress_turn = max(turns_recorded)
                    else:
                        # No turn metadata — legacy completed_events_json
                        # rows predating v0.2.2. We can't recover the real
                        # turn so we treat the last progress as turn 0,
                        # which means turns_since_progress == current_turn.
                        # This is conservative but correct: if a session has
                        # been alive for many turns and only recently been
                        # upgraded to v0.2.2, it almost certainly is stuck
                        # (matches the 72-turn-stuck real-play scenario that
                        # motivated this feature).
                        last_progress_turn = 0
                    turns_since_progress = current_turn - last_progress_turn

                    if turns_since_progress >= 3:
                        next_idx, next_event = pending_main_pairs[0]
                        emit_tag = (
                            f'<event_complete chapter="{sp.current_chapter}" '
                            f'event="{next_idx}" type="main"/>'
                        )
                        urgency = "❗❗ 极度紧急" if turns_since_progress >= 6 else "⚠️ 剧情强推"
                        parts.append(
                            f"## {urgency}（已 {turns_since_progress} 回合无主线进展）\n"
                            f"**本回合必须完成主线事件**：「{_render_event(next_event)}」\n\n"
                            f"操作步骤（严格按顺序）：\n"
                            f"1. 立刻安排 NPC 或环境事件将 PC 引向该主线事件（1-2 句即可）\n"
                            f"2. 在 narrative 中演出该事件的核心一幕（≤150 字，抓住最戏剧性的瞬间）\n"
                            f"3. **核心一幕演完后，立刻输出以下 tag（在当前回合任意位置均可，无需等叙事结束）**：\n"
                            f"```\n{emit_tag}\n```\n"
                            f"4. emit 完成后可继续补充叙事细节或 choices，但 event_complete 不能推到下回合\n\n"
                            f"⚠️ 误区纠正：event_complete 是**进度标记**，不是叙事终止符。"
                            f"你不需要等「整个事件叙事结束」才 emit——演出核心即标记完成。\n"
                            f"**如本回合未 emit 该 tag，系统视为未完成，下回合继续强推。**"
                        )

        # v0.10.5 — 本章主要场所 + 主要 NPC 常驻场所。受铁律 36 约束：
        # GM 在引入新 NPC 时若 PC 不在 NPC 的 primary_location，必须先 emit
        # `<plot_event type="encounter_setup">` 铺垫，否则 Python 软校验会
        # 把 ⚠️ NPC 凭空出场 警告写进 topology_warning_json，下回合反向提示。
        if isinstance(chapters, list) and chapters:
            cur_idx_v105 = max(0, min(sp.current_chapter - 1, len(chapters) - 1))
            cur_ch_v105 = (
                chapters[cur_idx_v105]
                if isinstance(chapters[cur_idx_v105], dict)
                else {}
            )
            main_locs = cur_ch_v105.get("main_locations") or []
            if isinstance(main_locs, list) and main_locs:
                loc_strs = [
                    str(loc).strip() for loc in main_locs[:6] if str(loc).strip()
                ]
                if loc_strs:
                    parts.append(
                        "\n## 本章主要场所（场景应主要在这些地方展开）\n"
                        + "\n".join(f"- {loc}" for loc in loc_strs)
                    )

        if isinstance(main_chars, list) and main_chars:
            primary_lines: list[str] = []
            for c in main_chars:
                if not isinstance(c, dict):
                    continue
                name = str(c.get("name") or "").strip()
                ploc = str(c.get("primary_location") or "").strip()
                if name and ploc:
                    primary_lines.append(f"- {name}：常驻 / 主活动于「{ploc}」")
            if primary_lines:
                parts.append(
                    "\n## 主要 NPC 常驻场所（PC 必须到这里才能首次相遇；"
                    "在场所外引入 NPC 必须先 emit "
                    "`<plot_event type=\"encounter_setup\">` 铺垫）\n"
                    + "\n".join(primary_lines)
                )

    # Hidden events — GM-only state with a fuse. Re-inject every turn so the
    # GM remembers an injury is still bleeding, a poison is still spreading,
    # a deadline is still ticking. The player never sees this section
    # directly; it's part of the system prompt.
    hidden = (
        await session.execute(
            select(HiddenEvent)
            .where(
                HiddenEvent.session_id == session_id,
                HiddenEvent.status == "active",
            )
            .order_by(HiddenEvent.introduced_turn)
        )
    ).scalars().all()
    if hidden:
        lines = ["\n## 暗中状态(GM only)"]
        for ev in hidden:
            age = current_turn - ev.introduced_turn
            sub = (ev.subject or "").strip() or "?"
            kind = (ev.kind or "").strip()
            desc = (ev.description or "").strip()
            cons = (ev.consequence or "").strip()
            tail = desc
            if cons:
                tail = f"{tail}。{cons}" if tail else cons
            lines.append(f"- [{sub}·{kind}·t+{age}] {tail}")
        parts.append("\n".join(lines))

    # v0.9 T7 — Faction reputation: inject active factions so GM knows
    # PC standing and can tune NPC attitudes / gate information accordingly.
    factions = (await session.execute(
        select(Faction).where(Faction.session_id == session_id)
    )).scalars().all()
    if factions:
        facts_lines = ["\n## 势力关系（PC 在各派系中的口碑）"]
        for f in factions:
            rep_label = "盟友" if f.pc_reputation >= 30 else ("敌人" if f.pc_reputation <= -30 else "中立")
            line = f"- {f.name}（{rep_label}, rep={f.pc_reputation}）"
            if f.ideology:
                line += f"：{f.ideology}"
            facts_lines.append(line)
        parts.append("\n".join(facts_lines))

    # PC hooks — abilities / items / weaknesses extracted from profile_md so
    # GM is reminded to actually use them in scenes.
    if character is not None:
        hooks = _extract_pc_hooks(character.profile_md or "")
        hook_lines: list[str] = []
        if hooks["abilities"]:
            hook_lines.append(
                "能力（应该被场景调用）：" + " / ".join(hooks["abilities"])
            )
        if hooks["items"]:
            hook_lines.append(
                "物品（应在剧情节点起作用）：" + " / ".join(hooks["items"])
            )
        if hooks["weaknesses"]:
            hook_lines.append(
                "弱点（应触发挑战）：" + " / ".join(hooks["weaknesses"])
            )
        if hook_lines:
            parts.append("## PC 钩子（用上它们）\n" + "\n".join(hook_lines))

    # PC numerical state — current attributes / level / inventory, surfaced
    # specifically as a "use this for DC and NPC attitude" reference.
    if character is not None:
        state_row = (
            await session.execute(
                select(CharState).where(CharState.session_id == session_id)
            )
        ).scalar_one_or_none()
        stats: dict = {}
        if state_row and state_row.stats_json:
            try:
                stats = json.loads(state_row.stats_json)
            except (TypeError, ValueError):
                stats = {}
        attr_pairs = [
            (k, v)
            for k, v in stats.items()
            if isinstance(v, (int, float))
            and k not in ("hp", "max_hp", "sanity", "max_sanity")
        ]
        level = character.level or 1
        inventory: list = []
        if state_row and state_row.inventory_json:
            try:
                inv_raw = json.loads(state_row.inventory_json)
                if isinstance(inv_raw, list):
                    inventory = inv_raw
            except (TypeError, ValueError):
                inventory = []

        if attr_pairs or level > 1 or inventory:
            num_lines = ["## PC 当前数值（dice / NPC 态度参考）"]
            if level > 1:
                num_lines.append(f"等级: Lv {level}")
            if attr_pairs:
                attr_str = " / ".join(f"{k}={v}" for k, v in attr_pairs)
                num_lines.append(f"属性: {attr_str}")
            if inventory:
                inv_str = "、".join(str(it) for it in inventory[:8])
                num_lines.append(f"物品: {inv_str}")
            num_lines.append(
                "（dice 检定的 DC 应基于属性合理设置；物品要在 narrative 显式引用；等级影响 NPC 态度。）"
            )
            parts.append("\n".join(num_lines))

    # v0.2.2 — dice monitoring. Pull recent assistant messages, extract any
    # d20 values from their events_json dice tags, and if the last 3+ are the
    # same value, surface a GM-only warning. Live play observed d20=9 repeated
    # 8 turns in a row, a textbook sign the model latched onto a constant.
    recent_msgs = (
        await session.execute(
            select(MessageRow)
            .where(
                MessageRow.session_id == session_id,
                MessageRow.role == "assistant",
            )
            .order_by(MessageRow.id.desc())
            .limit(5)
        )
    ).scalars().all()
    recent_msgs = list(reversed(recent_msgs))
    d20_values = extract_d20_values_from_messages(recent_msgs)
    stuck = detect_stuck_dice(d20_values, min_streak=2)
    if stuck is not None:
        parts.append(build_stuck_warning(d20_values, stuck))

    # v0.2.5 — Per-turn dynamic directive. Python-computed from current game
    # state; injected last so it's the freshest instruction before the GM writes.
    # Replaces the need for the LLM to self-diagnose pacing/variety issues.
    directive_items: list[str] = []

    # Scene stagnation: 3+ turns in same location → push for new element.
    # Suppressed when the structured scene pressure block (v0.3.0) is already
    # injecting a more authoritative directive above SCENE_SOFT_PRESSURE_TURNS.
    if current_loc is not None:
        turns_in_loc = current_turn - (current_loc.last_visited_turn or 0)
        stc_active = sess is not None and (sess.scene_turn_count or 0) >= SCENE_SOFT_PRESSURE_TURNS
        if turns_in_loc >= 3 and not stc_active:
            directive_items.append(
                f"场景节奏：PC 已在「{current_loc.name}」停留 {turns_in_loc} 回合，"
                "本回合必须加入打断元素（新NPC到来/意外发现/环境变化）或引导 PC 转移场景"
            )

    # NPC absence: pinned NPCs missing 5+ turns should be woven back in.
    for n in pinned_npcs:
        if current_turn > 0 and (current_turn - (n.last_seen_turn or 0)) >= 5:
            turns_absent = current_turn - (n.last_seen_turn or 0)
            directive_items.append(
                f"NPC 回场：{n.name} 已 {turns_absent} 回合未出现"
                f"（上次第 {n.last_seen_turn} 回合），本回合安排其主动联系或被提及"
            )

    # Narrative variety rotation — prevents the GM from defaulting to the
    # same prose pattern every turn. Cycles through 4 different requirements.
    _VARIETY = [
        "叙事质感：本回合融入一个具体感官细节（声音/气味/触感/温度），自然嵌入，不要单独列出",
        "叙事质感：安排一件出乎 PC 预料的小事或 NPC 意外反应，打破本回合的既定节奏",
        "叙事质感：在本回合末尾埋下一个未解答的悬念或细节，让玩家带着好奇进入下一回合",
        "叙事质感：聚焦情绪落差——同一场景内从平静到紧张（或反向）的节奏转变",
    ]
    directive_items.append(_VARIETY[current_turn % len(_VARIETY)])

    parts.append("## 🎬 本回合要点\n" + "\n".join(f"- {d}" for d in directive_items))

    return "\n".join(parts)
