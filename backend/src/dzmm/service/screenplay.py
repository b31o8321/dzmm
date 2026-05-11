# ============================================================
# screenplay.py — 剧本大纲生成、进度追踪与改写
# ============================================================
# 【什么是剧本（Screenplay）？】
#   剧本是游戏故事的"骨架"——由 LLM 在新建档时预先生成，包含：
#   - chapters: 章节列表，每章有若干待触发的事件
#   - main_characters: 主要 NPC 及其常驻场所
#   - ending: 故事的预定结局
#   - opening_hook: 开场钩子（吸引玩家继续的第一幕）
#
# 【为什么要有剧本？】
#   没有剧本的 AI-GM 很容易"随便发挥"，导致故事散乱、毫无目的感。
#   剧本给 GM 提供了目标和约束：你要推进哪些事件、最终走向哪里。
#   玩家的重大决策会触发剧本改写（rewrite），让故事分支保持连贯。
#
# 【剧本改写机制】
#   当玩家做出重大决策（如拒绝了主线任务），剧本后续章节需要重写。
#   rewrite_in_background 在后台异步完成改写，不阻断当前回合。
# ============================================================
import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Character,          # 玩家角色
    Screenplay,         # 剧本大纲
    ScreenplayRevision, # 剧本改写记录
    Session as GameSession,
    World,
)
from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.outliner_template import build_outliner_messages, build_rewrite_messages

log = logging.getLogger(__name__)

# 正则：剥除 LLM 返回的 markdown 代码块围栏（```json ... ```）
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
# 剧本 JSON 必须包含的顶层键
_REQUIRED_KEYS = {"chapters", "main_characters", "ending", "opening_hook"}


def _strip_fence(text: str) -> str:
    # 如果文本被 ``` 围栏包裹，去掉围栏只返回内容
    text = text.strip()
    m = _FENCE_RE.match(text)
    if m:
        return m.group(1).strip()
    return text


def _parse_outline_json(raw: str) -> dict:
    # 把 LLM 返回的原始文本解析成剧本 dict
    # 若格式不合法（JSON 损坏、缺少必填键、chapters 为空），抛出 ValueError
    cleaned = _strip_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"outliner returned invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"outliner returned non-object root: {type(data).__name__}")
    # 验证必需字段是否都存在
    missing = _REQUIRED_KEYS - data.keys()
    if missing:
        raise ValueError(f"outliner JSON missing keys: {missing}")
    # chapters 必须是非空列表（至少有一章）
    if not isinstance(data["chapters"], list) or not data["chapters"]:
        raise ValueError("outliner JSON 'chapters' must be a non-empty list")
    return data


async def generate_screenplay(
    session: AsyncSession,
    session_id: int,
    genre: str,          # 游戏类型（如"悬疑探案"）
    custom_prompt: str,  # 用户自定义的故事方向
    client: ModelClient,
    *,
    parent_screenplay_id: int | None = None,  # 续作时指向前作剧本的 ID
    previous_ending: str = "",                 # 前作的结局文本（续作起点）
) -> Screenplay:
    # 调用大纲生成 LLM，解析 JSON，持久化一条 Screenplay 行
    #
    # 【续作支持】
    #   previous_ending 非空时，把前作结局加入 Prompt，要求 LLM 在此基础上续写
    sess = await session.get(GameSession, session_id)
    if sess is None:
        raise ValueError(f"session {session_id} not found")
    world = await session.get(World, sess.world_id)
    char = await session.get(Character, sess.character_id)

    # 如果是续作，把前作结局附加到用户自定义 Prompt 后面
    user_extra = custom_prompt
    if previous_ending:
        user_extra = (custom_prompt or "") + (
            f"\n\n# 上一章结局（续作起点）\n{previous_ending}\n"
            "请基于这个结局生成下一章的剧情大纲。PC 状态延续，但章节、事件、敌对势力都应该是新的。"
        )

    # 构造给大纲生成器的 Prompt（把世界观、角色、类型等信息组合进去）
    messages = build_outliner_messages(
        world_name=world.name if world else "",
        world_md=world.content_md if world else "",
        character_name=char.name if char else "",
        character_md=char.profile_md if char else "",
        genre=genre or "悬疑探案",
        custom_prompt=user_extra,
    )

    from dzmm.service.activity_log import log_event
    import time as _time

    # 记录开始生成剧本的活动日志
    log_event(session_id, "screenplay_generate_start", genre=genre,
              parent_screenplay_id=parent_screenplay_id)
    start = _time.monotonic()  # 记录开始时间，用于计算耗时

    # 使用流式接口逐 token 接收 LLM 输出（大纲可能较长，流式减少等待感知）
    raw_chunks: list[str] = []
    try:
        async for chunk in client.stream(messages, GenerationParams(max_tokens=2000, temperature=0.7)):
            if chunk.delta:
                raw_chunks.append(chunk.delta)
    except Exception as e:
        # 生成失败：记录错误日志并重新抛出
        log_event(session_id, "screenplay_generate_error",
                  duration_ms=int((_time.monotonic() - start) * 1000),
                  error=str(e)[:200])
        raise
    raw = "".join(raw_chunks)  # 拼接所有 token 块为完整文本
    duration_ms = int((_time.monotonic() - start) * 1000)

    # 解析 LLM 返回的 JSON
    try:
        data = _parse_outline_json(raw)
    except ValueError as e:
        log_event(session_id, "screenplay_generate_error",
                  duration_ms=duration_ms, raw_chars=len(raw),
                  error=f"parse: {e}"[:200])
        raise

    # 把解析结果写入数据库
    sp = Screenplay(
        session_id=session_id,
        version=1,                          # 初始版本号
        genre=genre,
        custom_prompt=custom_prompt[:2000], # 截断，防止过长
        chapters_json=json.dumps(data["chapters"], ensure_ascii=False),
        main_characters_json=json.dumps(data["main_characters"], ensure_ascii=False),
        ending_md=str(data["ending"])[:2000],
        opening_hook=str(data["opening_hook"])[:2000],
        outline_md="",                      # 保留字段，目前用结构化 JSON 代替
        current_chapter=1,                  # 从第 1 章开始
        completed_events_json="[]",         # 初始时没有已完成的事件
        parent_screenplay_id=parent_screenplay_id,
        status="active",
    )
    session.add(sp)
    await session.flush()  # flush 使 sp.id 被赋值，但不 commit（由调用方决定是否提交）
    log.info(
        "generated screenplay %d for session %d (%d chapters, genre=%s, %dms, %d chars)",
        sp.id, session_id, len(data["chapters"]), genre, duration_ms, len(raw),
    )
    # 记录生成完成的活动日志
    log_event(session_id, "screenplay_generate_end",
              duration_ms=duration_ms, raw_chars=len(raw),
              num_chapters=len(data["chapters"]),
              num_main_characters=len(data["main_characters"]))
    return sp


async def get_active_screenplay(session: AsyncSession, session_id: int) -> Screenplay | None:
    # 返回指定存档当前活跃的剧本（version 最高的 active 状态行）
    # 改写时旧剧本也保留但 status 变为 "archived"，所以要按版本排序取最新
    stmt = (
        select(Screenplay)
        .where(
            Screenplay.session_id == session_id,
            Screenplay.status == "active",
        )
        .order_by(Screenplay.version.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def rewrite_screenplay_after_decision(
    session: AsyncSession,
    session_id: int,
    revision_id: int,           # ScreenplayRevision 行的 ID（由调用方预先创建）
    decision_description: str,  # 触发改写的重大决策描述
    client: ModelClient,
) -> ScreenplayRevision | None:
    # 调用大纲 LLM 重写活跃剧本当前章节之后的部分，
    # 填写改写记录（ScreenplayRevision）的 after_chapters_json 和 diff_summary，
    # 并原地更新剧本的 chapters_json。
    #
    # 【幂等语义】
    #   成功时返回 revision 行；失败时返回 None，revision 保留占位符 diff_summary，
    #   调用方可以通过检查 diff_summary 判断改写是否完成。
    rev = await session.get(ScreenplayRevision, revision_id)
    if rev is None:
        return None
    sp = await session.get(Screenplay, rev.screenplay_id)
    if sp is None or sp.status != "active":
        return None  # 剧本不存在或已不活跃，跳过
    sess = await session.get(GameSession, session_id)
    if sess is None:
        return None
    world = await session.get(World, sess.world_id) if sess.world_id else None
    char = await session.get(Character, sess.character_id) if sess.character_id else None

    # 把已完成的事件格式化成摘要文字，告诉 LLM"这些已经发生了，不要再写"
    completed_events = []
    try:
        completed_events = json.loads(sp.completed_events_json or "[]")
    except (ValueError, TypeError):
        pass
    completed_summary_lines = [
        f"- 第 {ev.get('chapter', '?')} 章 {ev.get('type', '')} 事件 #{ev.get('event_idx', '?')}（回合 {ev.get('turn', '?')}）"
        for ev in completed_events[:20]  # 最多列出 20 个，避免 Prompt 过长
    ]
    completed_summary = "\n".join(completed_summary_lines)

    # 构造改写 Prompt（包含原有章节 JSON + 触发决策 + 已完成事件）
    messages = build_rewrite_messages(
        world_name=world.name if world else "",
        world_md=world.content_md if world else "",
        character_name=char.name if char else "",
        character_md=char.profile_md if char else "",
        genre=sp.genre or "悬疑探案",
        current_chapters_json=sp.chapters_json or "[]",
        current_chapter=sp.current_chapter,
        completed_events_summary=completed_summary,
        decision_description=decision_description,
        custom_prompt=sp.custom_prompt or "",
    )

    from dzmm.service.activity_log import log_event
    import time as _time

    log_event(session_id, "screenplay_rewrite_start",
              screenplay_id=sp.id, revision_id=rev.id,
              trigger=decision_description[:100])
    start = _time.monotonic()

    # 流式接收 LLM 输出
    raw_chunks: list[str] = []
    try:
        async for chunk in client.stream(messages, GenerationParams(max_tokens=2000, temperature=0.7)):
            if chunk.delta:
                raw_chunks.append(chunk.delta)
    except Exception as e:
        log_event(session_id, "screenplay_rewrite_error",
                  duration_ms=int((_time.monotonic() - start) * 1000),
                  revision_id=rev.id, error=str(e)[:200])
        return None  # 失败时返回 None，让调用方处理
    raw = "".join(raw_chunks)
    duration_ms = int((_time.monotonic() - start) * 1000)

    # 解析新章节 JSON
    try:
        data = _parse_outline_json(raw)
    except ValueError as e:
        log_event(session_id, "screenplay_rewrite_error",
                  duration_ms=duration_ms, raw_chars=len(raw),
                  revision_id=rev.id, error=f"parse: {e}"[:200])
        return None

    new_chapters_json = json.dumps(data["chapters"], ensure_ascii=False)
    # diff_summary：改写摘要（LLM 生成或自动拼接），记录改写原因
    diff_summary = str(data.get("diff_summary") or "")[:500]
    if not diff_summary:
        diff_summary = f"基于决定『{decision_description[:80]}』改写第 {sp.current_chapter} 章起后续章节"

    # 把改写结果写入 ScreenplayRevision 记录（便于回溯对比）
    rev.after_chapters_json = new_chapters_json
    rev.diff_summary = diff_summary
    # 原地更新剧本的 chapters_json（当前章节之后用新版本）
    sp.chapters_json = new_chapters_json
    # 如果 LLM 也重写了结局/主角，一并更新
    if data.get("ending"):
        sp.ending_md = str(data["ending"])[:2000]
    if data.get("main_characters"):
        sp.main_characters_json = json.dumps(data["main_characters"], ensure_ascii=False)

    log_event(session_id, "screenplay_rewrite_end",
              duration_ms=duration_ms, raw_chars=len(raw),
              revision_id=rev.id, screenplay_id=sp.id,
              num_chapters=len(data["chapters"]))
    log.info(
        "rewrote screenplay %d (revision %d) for session %d (%dms, %d chars, %d chapters)",
        sp.id, rev.id, session_id, duration_ms, len(raw), len(data["chapters"]),
    )
    return rev


async def rewrite_in_background(
    session_maker,           # SQLAlchemy AsyncSessionMaker，用于开启新的数据库会话
    session_id: int,
    revision_id: int,
    decision_description: str,
) -> None:
    # 在后台（fire-and-forget）执行剧本改写
    # 开启一个新的 AsyncSession（不用调用方的会话，避免冲突）
    # 从存档的 GM 模型配置里构建 LLM 客户端，超时设为至少 600 秒
    # 改写成功后提交；失败时吞掉异常（记录日志），调用方不感知
    #
    # 【为什么在后台执行？】
    #   剧本改写可能需要 10~30 秒，不能让玩家等待。
    #   火后即忘（fire-and-forget）让当前回合立即返回，
    #   改写在后台悄悄完成，下一回合 Prompt 就会反映新剧本。
    from dzmm.db.models import ModelConfig as _MC, Session as _GS  # 本地导入：避免循环依赖
    from dzmm.models.factory import build_client as _build

    try:
        async with session_maker() as s:  # 开启一个独立的数据库会话
            sess = await s.get(_GS, session_id)
            if sess is None:
                return
            cfg = await s.get(_MC, sess.gm_model_config_id) if sess.gm_model_config_id else None
            if cfg is None:
                log.warning("rewrite_in_background: no GM model config for session %d", session_id)
                return
            client = _build(cfg)  # 根据模型配置创建 LLM 客户端
            # 改写任务可能很慢，确保超时至少 600 秒
            if hasattr(client, "timeout"):
                client.timeout = max(getattr(client, "timeout", 0.0), 600.0)
            result = await rewrite_screenplay_after_decision(
                s, session_id, revision_id, decision_description, client,
            )
            if result is not None:
                await s.commit()  # 改写成功才提交
    except Exception as e:  # noqa: BLE001
        # 吞掉异常，仅记录错误，不影响调用方
        log.error(
            "rewrite_in_background failed (session=%d, revision=%d): %s",
            session_id, revision_id, e,
        )
