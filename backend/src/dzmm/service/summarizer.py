# ============================================================
# summarizer.py — 对话历史摘要器
# ============================================================
# 【为什么需要摘要器？】
#   LLM（大语言模型）在处理超长对话时有两个问题：
#   1. 每次调用都要传入全部历史，消耗大量 token，速度慢、费用高
#   2. 模型对"很久之前"的内容注意力下降，回复质量变差
#
#   解决方案：每隔若干回合，把较早的对话压缩成一段文字摘要，
#   只把摘要 + 最近几轮原文传给模型，而不是所有原文。
#   这样 token 用量保持可控，同时关键情节不丢失。
# ============================================================

import re
from datetime import datetime, UTC

from sqlalchemy import select                        # SQLAlchemy 查询构造器
from sqlalchemy.ext.asyncio import AsyncSession     # 异步数据库会话

from dzmm.db.models import (
    Message as MessageRow,   # 数据库里的消息行（每条玩家/GM 消息）
    Session as GameSession,  # 游戏存档（别与 Python/HTTP Session 混淆）
    StorySummary,            # 存储摘要文本的表
)
from dzmm.models.client import GenerationParams, ModelClient  # LLM 调用参数和客户端
from dzmm.prompts.summarizer_template import (
    build_compression_messages,   # 构建"压缩摘要"Prompt 的函数
    build_summarizer_messages,    # 构建"生成新摘要"Prompt 的函数
)


# 每隔多少回合触发一次摘要（1 回合 = 1 条玩家消息 + 1 条 GM 回复 = 2 行）
SUMMARIZE_AFTER_TURNS = 10
# v0.2.1 — 长上下文修复。每积累 10 回合新内容触发一次
# （两个常量值相同，但分开命名是为了让意图更清晰，便于测试单独调整）
SUMMARIZE_TRIGGER_TURNS = 10
# 保留最近 N 回合不压缩，让 GM 有完整的即时场景上下文。
# （实际的"最近消息窗口"逻辑在 service/messages._load_recent_messages 里，
#   这里只是记录设计意图，方便维护者同步调整两处参数）
SUMMARIZE_KEEP_RECENT = 6
SUMMARY_MAX_TOKENS = 1000       # 足够容纳 600-800 字摘要和事实清单，限制长局维护长尾
COMPRESSION_TRIGGER_CHARS = 4000  # 摘要超过这个字符数才再次压缩
COMPRESSED_TARGET_TOKENS = 800   # 压缩后的目标 token 数


# 正则：从 LLM 返回的压缩文本里提取 <event importance="N">...</event> 标签
# re.IGNORECASE 让标签名大小写不敏感；[\s\S]*? 匹配任意字符（含换行）
_EVENT_RE = re.compile(r'<event\s+importance="(\d+)">([\s\S]*?)</event>', re.IGNORECASE)


# ── 内部辅助：把过长的摘要再次压缩 ──────────────────────────────────────────
async def _compress_summary(client: ModelClient, long_summary: str) -> tuple[str, list[dict]]:
    # 返回 (新摘要文本, 提取出的事件列表)。事件列表每项是 {importance, text}
    # 这个函数在"摘要本身也变得太长"时被调用，对摘要进行二次精简
    msgs = build_compression_messages(long_summary)
    # 以较低温度（0.2）生成，更保守、更确定，避免压缩时凭空捏造情节
    text, _usage = await client.complete(
        msgs, GenerationParams(temperature=0.2, max_tokens=COMPRESSED_TARGET_TOKENS + 200)
    )

    # 先从返回文本里提取所有 <event> 标签，作为结构化"重要事件"记录
    events: list[dict] = []
    for m in _EVENT_RE.finditer(text):
        try:
            imp = int(m.group(1))   # 解析 importance 属性的数字值
        except ValueError:
            continue
        # 重要性限制在 1~3 范围内（防止 LLM 返回异常值）
        events.append({"importance": max(1, min(3, imp)), "text": m.group(2).strip()})

    # 新摘要 = 第一个 <event 标签之前的所有文字；若没有 event 标签则取全文
    cut = text.find("<event")
    new_summary = text[:cut].strip() if cut >= 0 else text.strip()
    return new_summary, events


# ── 主入口：判断是否需要摘要，需要则执行 ────────────────────────────────────
async def maybe_summarize(
    session: AsyncSession,  # SQLAlchemy 异步会话，用于数据库读写
    session_id: int,        # 游戏存档 ID
    client: ModelClient,    # LLM 客户端（可以是 Ollama 或 OpenAI 兼容接口）
) -> bool:
    # 如果满足条件，执行一次摘要并返回 True；否则返回 False
    """Run a summarization pass if conditions are met. Returns True if executed."""

    # 先从数据库读取游戏存档行
    sess = await session.get(GameSession, session_id)
    # 存档不存在，或回合数还没到触发阈值 → 不摘要
    if sess is None or sess.turn_count < SUMMARIZE_TRIGGER_TURNS:
        return False

    # 查找已有的摘要行（一个存档对应一行摘要）
    summary_row = (
        await session.execute(
            select(StorySummary).where(StorySummary.session_id == session_id)
        )
    ).scalar_one_or_none()
    # high_water：上次摘要到的最后一条消息 ID，本次只处理这之后的新消息
    high_water = summary_row.last_summarized_msg_id if summary_row else 0

    # 读取上次摘要后的全部新消息（按 ID 升序）
    new_msgs = (
        await session.execute(
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .where(MessageRow.id > high_water)  # 只取新增部分
            .order_by(MessageRow.id)
        )
    ).scalars().all()

    # v0.2.1 — 用"回合数 × 2"而非固定消息数作为触发条件
    # （1 回合 = 用户消息 + 助手回复 = 2 行，所以乘以 2）
    # 旧阈值 20 条消息导致实际上要 20 回合才触发，长对话体验差
    if len(new_msgs) < SUMMARIZE_TRIGGER_TURNS * 2:
        return False

    # 把新消息拼成纯文本，格式：[role] content（每段用空行分隔）
    new_text = "\n\n".join(
        f"[{m.role}] {m.content}" for m in new_msgs
    )
    # 读取之前已有的摘要文本（若无则为空字符串）
    prev = summary_row.summary_text if summary_row else ""

    # 构造给 LLM 的摘要 Prompt：旧摘要 + 新消息 → 生成新的综合摘要
    msgs = build_summarizer_messages(
        previous_summary=prev,
        new_messages_text=new_text,
        key_facts="",  # 关键事实区块（此处留空，由 Prompt 模板负责注入）
    )

    # 调用 LLM 生成摘要，温度 0.3（稍有创意但主要保持忠实原文）
    summary_text, usage = await client.complete(
        msgs, GenerationParams(temperature=0.3, max_tokens=SUMMARY_MAX_TOKENS)
    )

    # 如果生成的摘要超过 4000 字符，说明摘要本身也过长，需要二次压缩
    events_to_persist: list[dict] = []
    if len(summary_text) > COMPRESSION_TRIGGER_CHARS:
        # 二次压缩：把摘要再精简，同时提取结构化"重要事件"列表
        summary_text, events_to_persist = await _compress_summary(client, summary_text)

    # 如果数据库里还没有摘要行，就新建一行并加入会话
    if summary_row is None:
        summary_row = StorySummary(session_id=session_id)
        session.add(summary_row)

    # 把最新摘要写入数据库
    summary_row.summary_text = summary_text.strip()
    # 记录这次摘要覆盖到了哪条消息（下次只处理这之后的新消息）
    summary_row.last_summarized_msg_id = new_msgs[-1].id
    # 记录本次摘要消耗的 token 数（供监控/计费使用）
    summary_row.summary_tokens = usage.output_tokens
    # 更新时间戳（replace(tzinfo=None) 去掉时区信息，与数据库列类型匹配）
    summary_row.updated_at = datetime.now(UTC).replace(tzinfo=None)

    return True
