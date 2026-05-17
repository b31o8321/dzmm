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

import json       # 用于解析/序列化 JSON 字符串（NPC 设定、历史消息、事件 payload 等都用 JSON 存储）
import logging     # Python 标准日志库，用 log.info / log.warning 记录运行时信息
import random      # 生成随机数：预掷 d20 骰子、厄运值触发概率
import re          # 正则表达式：用于修复 PC 名称漂移、检测 XML 标签、解析 Markdown
from collections.abc import AsyncIterator  # 异步迭代器类型提示，run_turn 的返回类型
from datetime import datetime, UTC         # 记录回合完成时间戳（写入 session.last_played）

# SQLAlchemy 是 Python 最流行的 ORM（对象关系映射）库
# select() 构建 SELECT 查询；AsyncSession 是异步数据库会话
# 【事务概念】AsyncSession 默认开启一个事务：你 add/update 对象后，
#   调用 await session.commit() 才真正写入数据库；
#   await session.flush() 把变更刷到数据库但不提交（可以拿到自增 id）；
#   如果抛出异常，调用 await session.rollback() 可以撤销所有未提交的变更。
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# 从数据库模型层导入 ORM 类——每个类对应数据库里的一张表
# 例如 Character 对应 characters 表，NPC 对应 npcs 表
from dzmm.db.models import (
    Character,    # 玩家角色（PC）信息表
    CharState,    # PC 动态状态：hp、sanity、inventory 等随游戏变化的数值
    Faction,      # 世界内的势力/派系，记录 PC 在各派系的声望值
    HiddenEvent,  # 仅 GM 可见的隐藏状态（中毒计时、NPC 秘密计划等）
    Location,     # 地点表：游戏世界里所有已登记的场所
    LocationEdge, # 地点拓扑边：记录两地点之间的方向/关系（如 A→B 通过隧道）
    Message as MessageRow,  # 对话消息表（user/assistant 回合历史）
    NPC,          # NPC 表：姓名、性格、好感度、当前位置等
    NpcRelation,  # NPC 与 NPC 之间的关系记录（如"A 是 B 的师父"）
    PCGoal,       # PC 当前目标列表（主线任务、支线任务）
    PlotThread,   # 进行中的剧情线（类型、重要度、状态描述）
    Screenplay,   # 剧本大纲：章节列表、完结条件、开场钩子
    Session as GameSession,  # 游戏会话（一次游玩记录）：turn_count、world_id 等
    StorySummary, # 故事摘要：summarizer 把早期历史压缩成文字摘要存在这里
    World,        # 世界设定表：世界观文档（Markdown）、风格、规则模式
    WorldLocation, # 开放世界预定义地点（含 connections_json travel_turns）
)
# ModelClient 是我们自己封装的 LLM 客户端接口，屏蔽了 OpenAI/Ollama/Claude 的差异
# Message 是 LLM 消息格式（role + content）；GenerationParams 是生成参数（温度/最大 token）
from dzmm.models.client import GenerationParams, Message, ModelClient, TokenUsage
# ParseEvent 是解析器产出的事件基类；NarrativeDelta 是流式文本片段；
# TagComplete 是一个完整的 XML 标签（如 <state_change hp="-5"/>）；
# UsageSummary 是 token 用量统计
from dzmm.parsing.events import NarrativeDelta, ParseEvent, TagComplete, UsageSummary
# StreamingTagParser：一个流式 XML 解析器，边接收 LLM token 边解析标签
# LLM 输出是字符串流，不能等全部输出再解析——所以需要流式解析器
from dzmm.parsing.stream_parser import StreamingTagParser
# build_gm_messages：把世界设定 + NPC + 历史消息拼成完整的 GM Prompt（system/user/assistant 消息列表）
from dzmm.prompts.gm_template import build_gm_messages
# build_outliner_messages：第一回合自动生成剧本大纲用的 Prompt
from dzmm.prompts.outliner_template import build_outliner_messages
# build_polish_messages：叙事润色（可选功能）的 Prompt
from dzmm.prompts.polish_template import build_polish_messages
# get_active_screenplay：查询当前会话的激活剧本
from dzmm.service.screenplay import get_active_screenplay
# get_world_md：获取世界观文档（支持 RAG 检索，只返回与当前行动相关的片段）
from dzmm.service.world_rag import get_world_md
# log_event：写入活动日志（前端"事件流"面板显示的内部日志）
from dzmm.service.activity_log import log_event
# find_initiative_npc：判断本回合结束后是否有 NPC 主动发起联系
from dzmm.service.npc_initiative import find_initiative_npc
# apply_tags：把本回合 LLM 产出的 XML 标签（state_change/npc_update/plot_event 等）
#   执行对应的数据库副作用（更新 HP、更新 NPC 好感度、推进剧情等）
from dzmm.service.state_apply import apply_tags
# format_world_time_cn：把 world_time_json 格式化成中文时间描述（如"第3天 · 深夜"）
from dzmm.service.state_apply.world_time import format_world_time_cn
# dice_monitor：检测 LLM 是否反复输出同一个骰子点数（实测有模型永远输出 d20=9 的 bug）
from dzmm.service.state_apply.dice_monitor import (
    build_stuck_warning,
    detect_stuck_dice,
    extract_d20_values_from_messages,
)


log = logging.getLogger(__name__)  # 创建以当前模块名为 name 的日志记录器，日志会归类到 dzmm.service.game

# ── 世界风格 → 剧本类型映射 ────────────────────────────────────────────────────
# 游戏世界有不同的基调（dark=黑暗、horror=恐怖、healing=治愈…）
# 生成剧本大纲时，要告诉 LLM 应该写哪种类型的故事结构，
# 这张映射表把世界风格翻译成 LLM 熟悉的中文故事类型标签。
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


# _update_scene_turn_count：追踪 PC 在同一地点连续停留了多少回合
# 用于驱动"场景节奏压力"机制：停留太久会触发强制推进剧情的提示词注入
# 参数 completed_tags：本回合 LLM 产出的所有已完成 XML 标签列表
def _update_scene_turn_count(sess, completed_tags: list) -> None:
    # any(...) 是 Python 的内置函数：只要生成器中有一个元素为真，立即返回 True（短路求值）
    # 这里检查本回合是否有 <location_enter> 标签——有的话说明 PC 进入了新地点
    # 【Java 对比】相当于 list.stream().anyMatch(t -> t.name.equals("location_enter"))
    location_entered = any(
        t.name == "location_enter" for t in completed_tags
    )
    if location_entered:
        sess.scene_turn_count = 1   # 进入新场景：重置计数器从 1 开始（1=刚到达）
    else:
        sess.scene_turn_count = sess.scene_turn_count + 1  # 同一场景：累加计数


# _recent_window_for：根据游戏进度自适应调整历史消息保留数量
# 游戏越长，摘要（StorySummary）的覆盖率越高，可以少保留原文来省 Token
# 这是一个纯函数（没有副作用），只根据回合数返回窗口大小
def _recent_window_for(turn_count: int) -> int:
    if turn_count > 60:
        return RECENT_WINDOW_VERY_LONG   # 老游戏：只保留最近 6 条消息
    if turn_count > 30:
        return RECENT_WINDOW_LONG_GAME   # 中期游戏：保留最近 8 条
    return RECENT_WINDOW_DEFAULT         # 新游戏：保留最近 12 条（没有摘要，需要更多原文）


# _rough_token_count：粗估整个 Prompt 消耗的 Token 数量
# 为什么粗估？因为精确计算（tiktoken）需要额外依赖且速度较慢。
# 这里的估算只用于日志告警，不需要精确，快速判断"是否超过 12k token"即可。
# 中文字符（CJK）约 1.5 个字 = 1 token；英文/ASCII 约 4 个字符 = 1 token
def _rough_token_count(messages: list[Message]) -> int:
    total = 0
    for m in messages:
        text = m.content or ""
        # sum() + 生成器表达式：统计文本中 CJK 字符的数量
        # "一" 到 "鿿" 是 Unicode 的中日韩统一表意文字范围（U+4E00 到 U+9FFF）
        cjk = sum(1 for c in text if "一" <= c <= "鿿")
        ascii_count = len(text) - cjk     # 剩余字符按 ASCII 估算
        total += int(cjk / 1.5) + int(ascii_count / 4)
    return total

# 预编译正则：匹配 <think>...</think> 标签（DeepSeek-R1 等推理模型的内部思考过程）
# re.DOTALL：让 . 也能匹配换行符（因为 <think> 可能跨多行）
# re.IGNORECASE：忽略大小写
# 预编译（compile）而不是每次调用 re.sub() 是为了性能——编译一次，复用多次
_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.DOTALL | re.IGNORECASE)


# _strip_thinking_tags：去除推理模型输出中的"思考过程"标签
# 部分推理增强模型（DeepSeek-R1、OpenAI o1）会把内部推理过程也输出出来
# 玩家不应该看到这些内部思考，只看到最终叙事
def _strip_thinking_tags(text: str) -> str:
    return _THINK_RE.sub("", text)  # 用空字符串替换所有匹配到的 <think> 块


# _assemble_full_output：把多 Agent 流式产出的事件列表拼装成完整的 XML 字符串
# 用途：把本回合所有内容合并成一条字符串，存到 messages.content（历史记录）
#
# 为什么需要"合并连续 NarrativeDelta"？
# LLM 是流式输出的：每次产出几个字组成一个 NarrativeDelta。
# 如果每个 delta 都单独包成 <narrative>浓</narrative><narrative>重</narrative>…
# 会产生数十个碎标签，下回合 LLM 读到历史时非常混乱。
# 解决方案：用 narrative_buf 缓存连续的文本片段，遇到非文本事件时一次性 flush 成一个标签。
def _assemble_full_output(events: list[ParseEvent]) -> str:
    parts: list[str] = []
    narrative_buf: list[str] = []  # 缓冲区：收集连续的叙事文本片段

    # 嵌套函数（闭包）：把缓冲区内容合并成一个 <narrative> 标签并清空缓冲区
    # 访问外层的 parts 和 narrative_buf——这就是 Python 闭包（closure）的特性
    def _flush_narrative() -> None:
        if narrative_buf:
            parts.append(f"<narrative>{''.join(narrative_buf)}</narrative>")
            narrative_buf.clear()  # list.clear() 原地清空，比重新赋值 [] 更高效

    for ev in events:
        if isinstance(ev, NarrativeDelta):
            narrative_buf.append(ev.text)    # 文本片段：先积累在缓冲区
        elif isinstance(ev, TagComplete):
            _flush_narrative()               # 遇到结构化标签：先把前面积累的叙事 flush 出去
            parts.append(_serialize_event_for_history(ev))  # 再序列化这个标签
    _flush_narrative()      # 循环结束后，把剩余缓冲区内容 flush（最后一段叙事可能没有后续标签）
    return "".join(parts)   # 把所有片段拼成一个字符串


# _serialize_event_for_history：把单个 ParseEvent 转换回 XML 字符串
# 用途：恢复成 XML 格式存入 messages 表，使得后续回合读取历史时能看到结构化标签
#
# 为什么要"恢复成 XML"？
# ParseEvent 是解析后的 Python 对象（便于程序处理），
# 但 messages.content 需要存储文本，下回合 LLM 读到历史时也需要看到 XML 标签——
# 因为 LLM 在训练（few-shot）时学会了"过去的 GM 输出是 XML 格式"的规律。
def _serialize_event_for_history(ev: ParseEvent) -> str:
    if isinstance(ev, NarrativeDelta):
        return f"<narrative>{ev.text}</narrative>"
    if isinstance(ev, TagComplete):
        # ev.attrs 是标签属性字典（如 {"hp": "-5", "reason": "中毒"}）
        # 用生成器表达式把字典转成 `key="value"` 格式，再用空格拼接
        attrs = " ".join(f'{k}="{v}"' for k, v in (ev.attrs or {}).items())
        if ev.content:
            # 有内容（如 <narrative>…文字…</narrative>）：生成开闭标签
            return (
                f"<{ev.name} {attrs}>{ev.content}</{ev.name}>"  # 有属性+有内容
                if attrs
                else f"<{ev.name}>{ev.content}</{ev.name}>"     # 无属性+有内容
            )
        # 无内容（如 <location_enter name="客栈"/>）：生成自闭标签
        return f"<{ev.name} {attrs}/>" if attrs else f"<{ev.name}/>"
    return ""  # 未知事件类型：返回空字符串（忽略）


# PC 姓名漂移修复（v0.1.6 重构后移到子模块，这里重新导出以保持向后兼容）
# 问题：LLM 有时会在 <pc_action> 标签里把 PC 称呼为错误的名字（如 PC 名叫 Riku，
#   但 GM 在第 7 回合的 <pc_action> 里写"我叫林峰"）。
# 解决：在持久化前用正则修复，使持久化的消息和后续渲染都使用正确名字。
# 注意：修复只影响数据库存储，流式输出已经发出给前端的内容无法撤回。
from dzmm.service.name_repair import (
    _NAME_PATTERNS,    # 正则模式列表：匹配各种错误的 PC 自我介绍写法
    _SAY_BLOCK_RE,     # 匹配 <say> 标签内容的正则（用于避免修改 NPC 台词）
    _repair_pc_name,   # 主修复函数：接收文本+正确名字，返回修复后的文本和修复次数
)


# _auto_generate_screenplay：第一回合自动调用 LLM 生成剧本大纲并存入数据库
# 这是「剧本驱动跑团」架构的核心初始化步骤：
#   - 输入：世界设定、角色卡、故事类型
#   - 输出：包含章节列表、主要 NPC、完结条件的 JSON 剧本大纲
#   - 存储：写入 Screenplay 表，后续每回合的 GM Prompt 都会引用这个大纲
# 【为什么是 async 函数？】
#   因为要 await LLM 流式调用和 await 数据库操作。
#   如果是同步函数，LLM 请求会阻塞整个进程——游戏服务器无法同时处理其他请求。
#   async/await 让 Python 在等待 LLM 响应时，可以切换去处理其他请求（并发）。
# 【Non-fatal 设计】：即使 LLM 返回格式错误，也只记录警告、使用降级模板，不抛出异常，
#   保证游戏能正常开始（健壮性优先于剧本质量）。
async def _auto_generate_screenplay(
    session: AsyncSession,  # 数据库异步会话（用来写入剧本到 DB）
    sess: GameSession,      # 当前游戏会话对象（需要它的 id 来关联剧本）
    world: World,           # 世界设定（提供世界名、设定文档、风格标签）
    char: Character,        # 角色（提供角色名和角色卡，让剧本能针对 PC 定制）
    client: ModelClient,    # LLM 客户端（用来调用 AI 生成剧本）
) -> None:
    # 根据世界风格查找对应的故事类型，找不到就用默认类型
    genre = _STYLE_TO_GENRE.get(world.style or "", _DEFAULT_GENRE)
    char_name = char.name or "PC"  # 防御性编程：name 可能为 None（数据库允许空值）

    # 构造"剧本大纲生成器"的 Prompt 消息列表
    # 【为什么要分 system/user/assistant？】
    #   这是 Chat Completion API 的三种角色：
    #   - system message：设定 AI 的身份和规则（如"你是一个创意编剧"），
    #                     由开发者写，用户看不到，优先级最高
    #   - user message：用户（或我们代表用户）的输入（如"请为这个世界生成剧本大纲"）
    #   - assistant message：AI 之前的输出（用于 few-shot 示例，教 AI 输出格式）
    #   分开三种角色让 LLM 更清楚自己的任务边界，比把所有内容塞进一条消息效果更好
    msgs = build_outliner_messages(
        world_name=world.name or "",
        world_md=world.content_md or "",
        character_name=char_name,
        character_md=_format_character_card(char),
        genre=genre,
    )

    # 流式接收 LLM 输出：async for 逐块消费 LLM 产出的 token
    # 【为什么用流式？】大模型生成 2000 token 的 JSON 可能需要 5-10 秒。
    # 流式接收允许服务器在等待过程中不阻塞，但这里只是往 buf 里收集，
    # 不向前端推送（剧本生成是内部操作，玩家感知不到）。
    buf: list[str] = []
    async for chunk in client.stream(msgs, GenerationParams(max_tokens=2000, temperature=0.7)):
        if chunk.delta:
            buf.append(chunk.delta)  # 把每个 token 片段追加到缓冲区

    raw = "".join(buf).strip()  # 把所有片段拼成完整字符串并去除首尾空白
    # LLM 有时会在 JSON 外面套 Markdown 代码块（```json ... ```），需要去掉
    # str.split("\n", 1)[-1] 含义：以换行符切割，最多切 1 次，取后半部分（即去掉第一行 ```）
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
    # str.rsplit("\n", 1)[0]：从右边切，去掉最后一行的 ``` 结尾
    if raw.endswith("```"):
        raw = raw.rsplit("\n", 1)[0]

    data: dict | None = None  # dict | None 是 Python 3.10+ 的联合类型写法（等价于 Optional[dict]）
    # 第一次尝试：直接解析整个字符串为 JSON
    # try/except 而不是先 if 再 parse，是"EAFP 风格"（Python 惯用法：请求宽恕而非先问许可）
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        pass  # 解析失败不抛出，继续尝试备用方案

    # 第二次尝试：用正则从文本中提取最外层的 {...} 块
    # 有时 LLM 会在 JSON 前后加上说明文字（如"以下是剧本大纲："），需要提取出纯 JSON 部分
    if data is None:
        m = re.search(r"\{.*\}", raw, re.DOTALL)  # re.DOTALL 让 . 能匹配换行
        if m:
            try:
                data = json.loads(m.group())  # m.group() 返回正则匹配到的字符串
            except (ValueError, TypeError):
                pass

    # 两次都失败：使用硬编码的降级骨架，确保游戏能启动
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
    # await session.flush()：把新建的 Screenplay 对象刷入数据库（但不提交事务）
    # flush 的作用：让 ORM 执行 INSERT 语句，分配自增 id，
    # 但事务仍未提交——调用方（run_turn）完成全部操作后统一 commit。
    # 这样可以保证"剧本生成" 和 "第一回合消息存储" 要么全部成功，要么全部回滚。
    await session.flush()
    log.info(
        "auto_screenplay: created for session %d (genre: %s, chapters: %d)",
        sess.id, genre, len(chapters),
    )


# 预编译正则：检测文本中是否包含任意一个游戏 XML 标签（用于检测 LLM 格式漂移）
# \b 是单词边界，防止误匹配（如 <narrative_extra> 不算 <narrative>）
_XML_TAG_RE = re.compile(r"<(narrative|say|pc_action|state_change|location_enter)\b")

# _check_xml_drift：检测 LLM 是否"忘记"了 XML 格式，并返回格式提醒字符串
#
# 为什么会发生格式漂移？
# 当 summarizer 把早期历史压缩成摘要后，上下文里的 XML 格式示例消失了。
# LLM 的输出风格会模仿它"看到"的历史——看不到 XML 样本，就退化成纯文本。
# 检测方法：反向扫描最近的 assistant 消息，如果连续 2 条都没有 XML 标签，
# 就向本回合的用户消息追加一段格式提醒（注入到 user message 而非 system，
# 因为 user 消息在很多模型中有更高的"当下指令"权重）。
def _check_xml_drift(recent_messages: list) -> str:
    plain_count = 0
    # reversed() 从最新的消息往前扫，遇到第一个有 XML 的 assistant 消息就停止
    for msg in reversed(recent_messages):
        if msg.role != "assistant":
            continue  # 只检查 assistant 消息（LLM 的输出）
        if _XML_TAG_RE.search(msg.content):
            break  # 找到了正确格式的回合，没有漂移，停止检查
        plain_count += 1
        if plain_count >= 2:
            # 连续 2 条 assistant 消息都是纯文本：确认漂移，返回提醒字符串
            return (
                "\n\n[GM 格式提醒] 请严格使用 XML 标签格式输出本回合内容："
                "旁白用 <narrative>…</narrative>，"
                "PC 行动用 <pc_action>…</pc_action>，"
                "NPC 对话用 <say speaker=\"NPC名\">…</say>。"
                "不要输出纯文本。"
            )
    return ""  # 没有漂移：返回空字符串（调用方拼接时为空字符串相当于不注入）


# ══════════════════════════════════════════════════════════════════════════════
# run_turn：游戏引擎核心函数——处理一个完整的游戏回合
# ══════════════════════════════════════════════════════════════════════════════
#
# 【一回合的完整流程】：
#   ① 从数据库读取当前状态（世界/角色/NPC/剧本/摘要）
#   ② 第一回合：调用 _auto_generate_screenplay 生成剧本大纲
#   ③ 调用 _build_key_facts 拼装 GM 需要的"当前游戏状态摘要"
#   ④ 注入特殊状态（厄运值/危急状态/内容分级/格式漂移提醒）
#   ⑤ v0.10 多 Agent 路径：交给 orchestrator 处理（Scene + NPC Actors）
#      OR
#      Legacy 单 Agent 路径：直接调用 build_gm_messages + LLM 生成
#   ⑥ 流式从 LLM 接收输出，边接收边解析 XML 标签，边 yield ParseEvent 给调用方
#   ⑦ 解析完毕：调用 apply_tags 执行所有状态变更（HP/NPC好感/地点/剧情等）
#   ⑧ 把玩家输入和 GM 输出写入 messages 表
#   ⑨ 更新 session 的 turn_count 和 last_played
#   ⑩ 检查是否有 NPC 主动发起联系，若有则额外 yield 一个 npc_initiative 事件
#
# 【为什么游戏服务要用 async/await？】
#   游戏服务器需要同时服务多个玩家。如果每个请求都同步等待 LLM（可能要 5-30 秒），
#   服务器在等待期间什么都做不了——第二个玩家的请求会被卡住。
#   async/await 使用 asyncio 事件循环：当 await LLM 时，控制权交还给事件循环，
#   让它去处理其他准备好的请求；LLM 返回后再切回来继续执行。
#   这就是"协作式多任务"——不需要多线程就能并发处理多个请求。
#
# 【函数签名说明】
#   session: AsyncSession → 数据库异步会话，函数内所有 DB 操作都用它
#   session_id: int       → 当前游戏会话的 ID（主键），用来查询该局游戏的所有数据
#   user_action: str      → 玩家本回合的输入文字（如"我推开门走进去"）
#   client: ModelClient   → 封装好的 LLM 客户端（支持多种模型后端）
#   params: GenerationParams | None → LLM 生成参数（温度、最大 token 等）
#   ollama_base_url: str | None  → 本地 Ollama 服务地址（用于 NPC 记忆 RAG 检索）
#   session_maker → 数据库 session 工厂（NPC Actor 子 Agent 需要独立 session）
#
async def run_turn(
    session: AsyncSession,
    session_id: int,
    user_action: str,
    client: ModelClient,
    params: GenerationParams | None = None,
    ollama_base_url: str | None = None,
    session_maker=None,
) -> AsyncIterator[ParseEvent]:
    # params=None 时使用默认参数（Python 惯用的"可选参数"写法）
    # 【Java 对比】相当于方法重载中的无参版本，或 Optional.orElse(new GenerationParams())
    params = params or GenerationParams()

    # ── ① 从数据库加载当前游戏状态 ────────────────────────────────────────────
    # session.get(Model, id) 是 SQLAlchemy 的主键查询，等价于 SELECT * WHERE id=?
    # await 在这里暂停当前协程，等待 DB I/O 完成（不阻塞其他请求）
    sess = await session.get(GameSession, session_id)
    if sess is None:
        raise ValueError(f"Session {session_id} not found")

    # 在回合开始时立即拍一份"状态快照"，存入本条消息记录
    # 用途：玩家"撤回上一回合"时，用这个快照把所有状态恢复到回合开始前
    # 快照包含：HP/san/属性、NPC好感度/情绪/位置、地点、剧情线、隐藏事件、派系声望等
    from dzmm.service.turn_snapshot import take_snapshot, serialize_snapshot
    snapshot_str = serialize_snapshot(await take_snapshot(session, session_id))

    world = await session.get(World, sess.world_id)        # 读取世界设定
    char = await session.get(Character, sess.character_id) # 读取角色卡

    # scalar_one_or_none()：查询最多返回一条记录；没有记录返回 None；
    # 有多条记录会抛出异常（CharState 是一对一关系，一个 session 只有一条）
    char_state = (
        await session.execute(
            select(CharState).where(CharState.session_id == session_id)
        )
    ).scalar_one_or_none()
    # 合并"基础属性"和"动态状态"成一个字典，供后续代码使用
    live_state = _build_live_state(char, char_state)

    # 读取已有的故事摘要（由后台 summarizer 定期生成）
    # 摘要把早期的对话历史压缩成文字，让 LLM 不需要看全部历史也能了解剧情背景
    summary_row = (
        await session.execute(
            select(StorySummary).where(StorySummary.session_id == session_id)
        )
    ).scalar_one_or_none()
    story_summary = summary_row.summary_text if summary_row else ""

    # ── ② 第一回合：自动生成剧本大纲 ──────────────────────────────────────────
    # sess.turn_count == 0 意味着这是第一回合（还没有任何消息历史）
    # 用 LLM 生成一个 3-5 章的剧本骨架，后续 GM 在每回合都会看到"当前章节进度"
    if sess.turn_count == 0:
        existing_sp = (await session.execute(
            select(Screenplay).where(
                Screenplay.session_id == session_id,
                Screenplay.status == "active",
            )
        )).scalar_one_or_none()
        if existing_sp is None:  # 防止重复生成（如果已存在就跳过）
            await _auto_generate_screenplay(session, sess, world, char, client)

    # ── ③ 拼装 GM 上下文（key_facts）───────────────────────────────────────────
    # key_facts 是注入到 GM Prompt 里的"游戏状态摘要"
    # 包含：当前回合、PC身份、世界时间、NPC 列表、剧情线、当前地点、剧本进度等
    # 这是 _build_key_facts 函数（在文件下方定义）的返回值
    key_facts = await _build_key_facts(
        session, session_id, sess.turn_count, char,
        ollama_base_url=ollama_base_url,
        user_action=user_action,
    )

    # 从 session.settings_json 读取玩家/GM 的会话级别设置
    # json.loads(... or "{}") 是防御性写法：字段为 NULL 时用空字典代替
    settings = json.loads(sess.settings_json or "{}")

    # ── ④-A 注入厄运值（Doom Meter）──────────────────────────────────────────
    # 厄运值是一个 0-100 的整数，由 apply_tags 在处理某些事件时递增。
    # 当厄运值较高时，GM Prompt 里会注入"末日氛围"描述，并按概率触发强制坏结局。
    # random.random() 返回 [0, 1) 的随机浮点数——用来实现"X% 概率触发"
    doom = sess.doom_score
    if doom > 0:
        if doom < 60:
            doom_note = f"## ⚠️ 压力值（仅GM可见）\n当前厄运值：{doom}/100（低风险，正常叙事）。"
        elif doom < 80:
            doom_note = f"## ⚠️ 压力值（仅GM可见）\n当前厄运值：{doom}/100（中等压力）。叙事基调偏阴沉，NPC 更紧张，事态更难控制。"
            if random.random() < 0.10:  # 10% 概率触发坏结局
                doom_note += "\n\n🔴 **坏结局触发**：本回合必须演出一个不可逆的恶化事件并 emit `<ending type=\"bad\">`。"
        elif doom < 90:
            doom_note = f"## ⚠️ 压力值（仅GM可见）\n当前厄运值：{doom}/100（高压力）。世界对PC持续恶化。"
            if random.random() < 0.25:  # 25% 概率触发坏结局
                doom_note += "\n\n🔴 **坏结局触发**：本回合必须演出一个不可逆的恶化事件并 emit `<ending type=\"bad\">`。"
        elif doom < 100:
            doom_note = f"## ⚠️ 压力值（仅GM可见）\n当前厄运值：{doom}/100（临界崩溃）。"
            if random.random() < 0.50:  # 50% 概率触发坏结局
                doom_note += "\n\n🔴 **坏结局触发**：本回合必须演出一个不可逆的恶化事件并 emit `<ending type=\"bad\">`。"
        else:
            # doom == 100：必然触发末日结局（100% 概率，不用 random）
            doom_note = f"## ⚠️ 压力值（仅GM可见）\n当前厄运值：100/100。\n\n🔴 **坏结局触发**：本回合必须演出末日事件并 emit `<ending type=\"bad\">`。"
        # 把厄运提示追加到 key_facts 末尾（GM Prompt 里 key_facts 放在最靠近生成指令的位置）
        key_facts = key_facts + "\n\n" + doom_note

    # ── ④-B 注入危急生命值提示 ────────────────────────────────────────────────
    # HP/sanity 的下限是 0（不会变负数，apply_tags 里有 clamp 逻辑）。
    # 问题：HP=0 后面板显示 PC 倒下，但 GM 没有任何信号，仍然继续正常叙事。
    # 解决：检测到 HP=0 或 sanity=0 时，强制注入"必须处理危急状态"的 GM 指令。
    crit_lines = []
    # live_state.get("hp") or 0：先 get 可能为 None，再 or 0 把 None 转成 0
    if (live_state.get("hp") or 0) <= 0:
        crit_lines.append("- HP=0：PC 已倒下 / 失去意识 / 濒死")
    if (live_state.get("sanity") or 0) <= 0:
        crit_lines.append("- sanity=0：PC 已陷入疯狂 / 精神崩溃")
    if crit_lines:
        # "\n".join(列表) 把列表元素用换行符拼接成字符串
        key_facts = key_facts + (
            "\n\n## 💀 危急状态（仅GM可见）\n"
            + "\n".join(crit_lines)
            + "\n\n🔴 **必须立即解决**：本回合任选其一——\n"
              "  (a) 演出救援/治疗/缓解事件，让对应数值恢复至 ≥1（state_change 加正值）；\n"
              "  (b) 演出 PC 倒下的最终结局并 emit `<ending type=\"bad\">`。\n"
              "禁止当作没事继续推进剧情。"
        )

    # ── ④-C 注入内容分级说明 ──────────────────────────────────────────────────
    # 默认是 safe 模式（不注入任何额外指令，使用 system prompt 的基础版本）
    # mature/unrestricted 模式由玩家在设置里开启，注入对应的内容许可说明
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

    # ── ④-D 加载最近历史消息 ──────────────────────────────────────────────────
    # 加载自上次摘要之后的最新 N 条对话（N 由 _recent_window_for 决定）
    # 这些消息会以 user/assistant 角色的形式放入 LLM 消息列表（让 LLM 记得最近发生了什么）
    recent = await _load_recent_messages(session, session_id, summary_row)

    # 如果摘要器尚未运行（游戏已经很长但没有摘要），注入警告提示
    # 防止 LLM 因为缺少背景信息而"凭空重置"剧情
    from dzmm.service.summarizer import SUMMARIZE_AFTER_TURNS
    if not story_summary and sess.turn_count > SUMMARIZE_AFTER_TURNS:
        key_facts = (
            "⚠️ 剧情摘要暂缺（摘要器尚未运行或失败）。"
            "请完全依赖下方的 recent messages 推断背景，"
            "保持当前场景的人物/地点/事件与消息历史一致，不要重置剧情或重新介绍已出现的 NPC。\n\n"
        ) + key_facts

    # ── ④-E 检测 XML 格式漂移并准备提醒字符串 ────────────────────────────────
    # xml_reminder 在漂移时是一段文字，否则是空字符串
    # 后面会把它拼接到 user_action 末尾注入 Prompt
    xml_reminder = _check_xml_drift(recent)

    # 从世界设定里读取规则模式：light（轻规则）或 strict（严格规则）
    # 影响 GM Prompt 里骰子判定规则的详细程度
    rules_mode = json.loads(world.rules_json or '{"mode":"light"}').get("mode", "light")

    # 格式化角色卡（等级+性别头部 + 截断的 profile_md）
    character_md = _format_character_card(char)

    # ── ⑤ 选择执行路径：v0.10 多 Agent 还是 Legacy 单 Agent ──────────────────
    # v0.10 多 Agent 架构：
    #   - Director Agent：分析本回合是否需要触发剧情推进/转折
    #   - Scene Agent：主叙事，流式输出叙事文字和主要 XML 标签
    #   - NPC Actor Agents：每个重要 NPC 独立一个 Agent，补充 NPC 的台词/行为
    # 这个 if 块处理 v0.10 路径（默认开启），后面的 else 分支是 Legacy 路径
    if settings.get("use_v10", True):
        # 延迟导入（import in function body）：只有在用到时才加载这个模块
        # 好处：避免循环导入，也让模块加载更快
        from dzmm.service.agents.orchestrator import run_turn_v10
        from dzmm.prompts.gm_template import _format_live_state

        # 把 live_state 字典格式化成 GM 可读的文本（如 "HP: 8/20 | 理智: 15/20"）
        live_state_text = _format_live_state(live_state)

        # 服务端预掷 d20 骰子——防止 LLM 自己"捏造"骰子结果（实测 LLM 会反复输出相同的数）
        # random.randint(1, 20) 是两端包含的随机整数，1 和 20 都可能出现
        # 把这个数字注入 key_facts，告诉 GM "本回合骰子是 X，必须用这个值"
        prerolled_d20 = random.randint(1, 20)
        key_facts = key_facts + (
            f"\n\n## 🎲 本回合系统骰子\n"
            f"**预掷 d20 = {prerolled_d20}**\n"
            f"若本回合需要技能判定，pc_roll 必须填这个值（不得自行生成其他数字）。"
        )

        # 收集所有事件的容器
        all_events: list[ParseEvent] = []      # 所有事件（用于拼装 full_output）
        completed_tags: list[TagComplete] = [] # 完整的结构化标签（用于 apply_tags）
        narrative_parts: list[str] = []        # 纯叙事文本片段（用于 PC 名字修复）
        v10_usage = UsageSummary()             # Token 用量汇总（多个 Agent 的总和）

        # 委托给 v0.10 Orchestrator 执行：它内部启动 Director + Scene + NPC Actors
        # async for：异步迭代，逐个消费 orchestrator yield 出来的 ParseEvent
        # 这里 run_turn_v10 也是 async generator，yield 一个事件时这里立即拿到并转发
        async for ev in run_turn_v10(
            session,
            session_id=session_id,
            user_action=user_action,
            scene_client=client,
            director_client=client,
            npc_client=client,
            session_maker=session_maker,  # NPC Actor 需要独立 session 并发运行
            world_md=get_world_md(
                world.id,
                world.content_md or "",
                user_action,
                ollama_base_url,   # 为 None 时禁用 RAG 检索，直接用全量世界观文档
            ),
            character_md=character_md,
            live_state_text=live_state_text,
            key_facts=key_facts,
            recent_messages=recent,
        ):
            if isinstance(ev, UsageSummary):
                v10_usage = ev    # 保存 token 用量，不向前端推送
                continue  # continue 跳过本次循环剩余代码，进入下一次迭代
            all_events.append(ev)
            if isinstance(ev, TagComplete):
                completed_tags.append(ev)     # 收集完整标签（后面 apply_tags 用）
            if isinstance(ev, NarrativeDelta):
                narrative_parts.append(ev.text)  # 收集叙事文本（后面名字修复用）
            yield ev  # 把事件转发给调用方（API 路由 → SSE → 前端），实现"打字机效果"

        # 把所有事件拼装成一条完整的 XML 字符串，存入 messages 表
        full_output = _assemble_full_output(all_events)
        next_turn = sess.turn_count + 1  # 下一回合编号（新消息的 turn 字段）

        # ── ⑦-⑧ 持久化消息和执行状态变更 ──────────────────────────────────────
        # session.add() 把对象加入 ORM 的"待写入"队列
        # 这里不会立即执行 SQL，等到调用方 commit() 时才真正写入
        session.add(MessageRow(
            session_id=session_id, role="user",
            content=user_action, turn=next_turn,  # 保存玩家的输入
        ))
        # 把本回合所有 TagComplete 事件序列化成 JSON 存入 events_json
        # 前端用这个字段渲染"事件芯片"（如 "HP -5" / "进入客栈" 等 UI 元素）
        events_payload = [
            {
                "type": tag.name,         # 标签类型（如 state_change、location_enter）
                "payload": dict(tag.attrs or {}),  # 标签属性（如 hp="-5"）
                "content": tag.content or "",      # 标签内容（如文字描述）
            }
            for tag in completed_tags  # 列表推导式：对每个 tag 生成一个字典
        ]
        session.add(MessageRow(
            session_id=session_id, role="assistant",
            content=full_output, turn=next_turn,
            events_json=json.dumps(events_payload, ensure_ascii=False),  # ensure_ascii=False 保留中文
            snapshot_json=snapshot_str,  # 回合开始时的状态快照（用于撤回）
            tokens_in=v10_usage.tokens_in,
            tokens_out=v10_usage.tokens_out,
        ))
        # v0.15.2 — forward usage summary to external consumers
        # (eval / playtest scripts). API SSE layer filters this out.
        yield UsageSummary(tokens_in=v10_usage.tokens_in, tokens_out=v10_usage.tokens_out)
        await apply_tags(session, session_id, next_turn, completed_tags)
        # v0.10.5 — soft validation: warn if a brand-new NPC appeared
        # outside their primary_location with no encounter_setup. Soft
        # only — never aborts the SSE stream.
        from dzmm.service.encounter_check import check_encounter_warnings
        await check_encounter_warnings(
            session, session_id, completed_tags, current_turn=next_turn,
        )
        # v0.15 — auto-trigger framework events whose structured predicates
        # are now satisfied. Inert for legacy free-text predicates.
        if sess.framework_id:
            from dzmm.service.event_evaluator import check_and_trigger_events
            await check_and_trigger_events(session, session_id, next_turn)
        _update_scene_turn_count(sess, completed_tags)
        # ── ⑨ 更新会话状态 ────────────────────────────────────────────────────
        sess.turn_count = next_turn         # 回合计数器 +1
        # datetime.now(UTC)：获取当前 UTC 时间（带时区信息）
        # .replace(tzinfo=None)：去掉时区信息（数据库列是不带时区的 DATETIME 类型）
        sess.last_played = datetime.now(UTC).replace(tzinfo=None)
        return  # 提前返回，跳过 Legacy 路径（async generator 里 return 等于 StopAsyncIteration）

    # ══════════════════════════════════════════════════════════════════════════
    # ── Legacy 单 Agent 路径（use_v10=False 时使用，或作为降级备选方案）────────
    # ══════════════════════════════════════════════════════════════════════════
    # 把 xml_reminder 拼接到玩家行动后面，作为 user message 的一部分注入 Prompt
    # 空字符串拼接相当于没有注入（不改变原始消息）
    action_with_reminder = user_action
    if xml_reminder:
        action_with_reminder = user_action + "\n\n" + xml_reminder
        log.info("injecting XML format reminder for session %d (drift detected)", session_id)

    # Legacy 路径也需要预掷骰子（和 v0.10 路径相同的逻辑）
    prerolled_d20 = random.randint(1, 20)
    key_facts = key_facts + (
        f"\n\n## 🎲 本回合系统骰子\n"
        f"**预掷 d20 = {prerolled_d20}**\n"
        f"若本回合需要技能判定，pc_roll 必须填这个值（不得自行生成其他数字）。"
    )

    # 条件性注入 GM 规则文档：只注入本回合"可能用到"的部分
    # 原因：GM Prompt 里有大量可选标签的文档（剧本/派系/战斗等），
    # 如果每回合全部注入，会白白消耗几百到几千个 token。
    # 所以先检测"本回合是否有剧本"、"是否有派系"、"是否在战斗中"，
    # 只注入对应的文档片段。
    sp_active = await get_active_screenplay(session, session_id)
    has_screenplay = sp_active is not None  # 布尔值：True=有剧本，False=没有
    # .limit(1) + scalar_one_or_none() is not None 是一种高效的"存在性检查"
    # 比 COUNT(*) 快，因为找到第一条就停止扫描
    has_factions = (
        await session.execute(
            select(Faction.id).where(Faction.session_id == session_id).limit(1)
        )
    ).scalar_one_or_none() is not None
    # 检测最近 5 回合是否有未关闭的战斗（有 combat_start 但没有 combat_end）
    has_combat_recent = await _detect_combat_recent(session, session_id, sess.turn_count)

    # ── ⑤-Legacy 构建 GM Prompt（消息列表）──────────────────────────────────
    # build_gm_messages 把所有材料拼成一个 Message 列表：
    #   msgs[0]: system message（GM 身份设定 + 游戏规则 + 输出格式要求）
    #   msgs[1..n-2]: few-shot examples（过去的对话历史，让 LLM 学习输出格式）
    #   msgs[n-1]: 当前 user message（玩家本回合行动 + key_facts + 游戏状态）
    # 这种"system + history + user"结构是 Chat Completion API 的标准用法
    msgs = build_gm_messages(
        world_md=get_world_md(       # 世界观文档（RAG 检索后的相关片段）
            world.id,
            world.content_md or "",
            user_action,             # 用玩家行动作为 RAG 查询词
            ollama_base_url,
        ),
        character_md=character_md,   # 角色卡文本
        live_state=live_state,       # PC 当前属性字典（hp/san/属性等）
        rules_mode=rules_mode,       # 规则模式（light/strict）
        style=world.style,           # 世界风格（dark/horror/healing 等）
        story_summary=story_summary, # 历史故事摘要文本
        key_facts=key_facts,         # 本回合 GM 上下文（NPC/剧情/地点等）
        recent_messages=recent,      # 最近 N 条对话历史
        current_action=action_with_reminder,  # 玩家行动（可能附加格式提醒）
        has_screenplay=has_screenplay,
        has_factions=has_factions,
        has_combat_recent=has_combat_recent,
    )

    # debug_mode 开启时，把完整 Prompt 序列化成 JSON 存入消息记录，便于调试
    _debug_prompt_json = ""
    if settings.get("debug_mode"):
        _debug_prompt_json = json.dumps(
            [{"role": m.role, "content": m.content} for m in msgs],
            ensure_ascii=False,
        )

    # 估算 Prompt token 数，记录到活动日志（超过 12k token 时发出警告）
    # 本地 7B 模型通常在超过 12k token 时开始出现"重复 few-shot 示例"的退化
    prompt_tokens = _rough_token_count(msgs)
    log_event(session_id, "turn_prompt_size",
              tokens=prompt_tokens, msgs=len(msgs))
    if prompt_tokens > 12000:
        log_event(session_id, "turn_prompt_warning",
                  tokens=prompt_tokens,
                  msg="prompt > 12k tokens, model may struggle with long context")

    # ── ⑥ 流式调用 LLM，边接收边解析 XML，边 yield 给前端 ────────────────────
    parser = StreamingTagParser()      # 流式 XML 解析器（有状态的，需要保持实例）
    full_output_parts: list[str] = []  # 原始输出所有 token 片段（最后拼成 full_output）
    completed_tags: list[TagComplete] = []  # 本回合所有完整的 XML 标签
    narrative_parts: list[str] = []    # 叙事文本片段（用于 PC 名字修复和润色）
    usage = TokenUsage()               # token 用量（从最后一个 chunk 获取）
    narrative_emitted = False          # 标记是否有叙事文本（用于 fallback 判断）

    # client.stream() 返回 async generator，每次 yield 一个 Chunk 对象
    # Chunk.delta: 本次的文本增量（可能是几个字符）
    # Chunk.usage: token 用量（通常只在最后一个 chunk 里非空）
    async for chunk in client.stream(msgs, params):
        if chunk.delta:
            full_output_parts.append(chunk.delta)  # 收集原始输出
            # parser.feed() 把新增文本喂给解析器，返回解析出的事件列表
            # 每个 delta 可能触发 0 个或多个事件（如一个 delta 恰好完成了一个标签）
            for ev in parser.feed(chunk.delta):
                if isinstance(ev, TagComplete):
                    completed_tags.append(ev)    # 收集完整标签
                if isinstance(ev, NarrativeDelta):
                    narrative_emitted = True
                    narrative_parts.append(ev.text)
                yield ev  # 关键：把事件 yield 给调用方（API → SSE → 前端打字机效果）
        if chunk.usage is not None:
            usage = chunk.usage  # 更新 token 用量（通常在最后一个 chunk 里出现）

    # parser.finish()：通知解析器输入结束，flush 内部缓冲区（处理未关闭的标签）
    # 有时 LLM 输出到最后一个 token 时标签还没完全关闭，finish() 会强制关闭
    for ev in parser.finish():
        if isinstance(ev, TagComplete):
            completed_tags.append(ev)
        if isinstance(ev, NarrativeDelta):
            narrative_emitted = True
            narrative_parts.append(ev.text)
        yield ev

    # 把所有 token 片段拼成完整字符串（用于存入数据库）
    full_output = "".join(full_output_parts)

    # Fallback：如果 LLM 没有输出任何 <narrative> 标签（纯文本输出或解析失败），
    # 把整个原始输出作为叙事文本 yield 出去，让前端至少能显示一些内容
    # 先去除 <think>...</think> 思考块（推理模型的内部过程不应该显示给玩家）
    if not narrative_emitted and full_output.strip():
        fallback = _strip_thinking_tags(full_output).strip()
        if fallback:
            narrative_parts.append(fallback)
            yield NarrativeDelta(fallback)  # 作为普通叙事文本 yield 给前端

    # ── PC 姓名漂移修复 ────────────────────────────────────────────────────────
    # 流式输出已经发出（玩家已经看到错误的名字），修复只影响 DB 存储和后续回合的上下文
    # 修复后 apply_tags 收到的文本是正确的名字，不会把错误名字传播到 NPC 关系图等
    if char is not None and char.name:
        full_output, n_fixes = _repair_pc_name(full_output, char.name)
        if n_fixes > 0:
            log.info(
                "repaired %d PC name drift(s) in turn %d", n_fixes, sess.turn_count
            )
            # 同步修复叙事文本片段，让后续润色和 apply_tags 都用正确的名字
            joined = "".join(narrative_parts)
            repaired_joined, _ = _repair_pc_name(joined, char.name)
            narrative_parts = [repaired_joined] if repaired_joined else []

    # ── 可选：叙事润色（narrative_polish 设置开启时）─────────────────────────
    # 用第二个 LLM 调用对叙事文字进行文学性改进，然后 yield narrative_revised 标签
    # 前端收到 narrative_revised 后，会用润色后的版本替换已显示的原始版本
    # 注意：这是"非流式"的二次调用（client.complete 而不是 client.stream），
    # 等待期间前端显示的仍是原始版本，润色完成后瞬间替换
    if settings.get("narrative_polish") and narrative_parts:
        raw_narrative = "".join(narrative_parts).strip()
        if raw_narrative:
            try:
                polish_msgs = build_polish_messages(raw_narrative)
                polished, _ = await client.complete(
                    polish_msgs, GenerationParams(temperature=0.4, max_tokens=800)
                )
                if polished.strip():
                    narrative_parts = [polished.strip()]   # 用润色结果替换原始文本
                    yield TagComplete(name="narrative_revised", content=polished.strip())
            except Exception as exc:  # noqa: BLE001
                # 润色失败不影响游戏继续（非致命错误），只记录警告
                log.warning("polish pass failed: %s", exc)

    # ── ⑧ 持久化消息（Legacy 路径）──────────────────────────────────────────
    next_turn = sess.turn_count + 1

    # NPC 长期记忆：把本回合 NPC 说的话（<say> 标签内容）异步存入向量数据库
    # 只在 ollama_base_url 非空时执行（需要本地 Ollama 服务来生成文本嵌入向量）
    # "fire-and-forget"：用 asyncio.create_task 创建后台任务，不等待完成
    # 【为什么不 await？】记忆存储可能需要几秒（嵌入计算），而本回合的响应不需要等它
    # asyncio.create_task 把协程调度到事件循环，run_turn 继续向前执行
    if ollama_base_url and completed_tags:
        from dzmm.service.npc_memory import record_memory as _record_npc_memory
        npc_rows_for_mem = (
            await session.execute(
                select(NPC).where(NPC.session_id == session_id)
            )
        ).scalars().all()
        # 字典推导式：把 NPC 列表转成"姓名→id"的映射字典，便于后面快速查找
        name_to_npc_id: dict[str, int] = {
            n.name: n.id for n in npc_rows_for_mem if n.name and n.id
        }
        for _tag in completed_tags:
            if _tag.name == "say":
                _speaker = _tag.attrs.get("speaker", "") if _tag.attrs else ""
                _npc_id = name_to_npc_id.get(_speaker)  # 查找说话者的 NPC id
                _text = (_tag.content or "").strip()
                # 只记录中等长度的台词（过短无意义，过长超出嵌入模型限制）
                if _npc_id and 20 < len(_text) <= 300:
                    asyncio.create_task(      # 启动后台任务，不阻塞当前流程
                        _record_npc_memory(_npc_id, next_turn, _text, ollama_base_url)
                    )

    # 保存玩家的行动输入（role="user"）
    session.add(MessageRow(
        session_id=session_id, role="user", content=user_action, turn=next_turn,
    ))

    # 把本回合所有结构化标签事件序列化成 JSON（前端用于渲染事件芯片 UI）
    events_payload = [
        {
            "type": tag.name,           # 标签类型
            "payload": dict(tag.attrs or {}),  # 标签属性
            "content": tag.content or "",      # 标签文本内容
        }
        for tag in completed_tags
    ]

    # 保存 GM 的输出（role="assistant"）
    # prompt_json 只在 debug_mode 时有内容（避免日常存储占用大量空间）
    session.add(MessageRow(
        session_id=session_id, role="assistant", content=full_output, turn=next_turn,
        tokens_in=usage.input_tokens, tokens_out=usage.output_tokens,
        events_json=json.dumps(events_payload, ensure_ascii=False),
        prompt_json=_debug_prompt_json,
        snapshot_json=snapshot_str,  # 本回合开始前的状态快照（用于撤回）
    ))

    # v0.15.2 — yield UsageSummary so external consumers (eval / playtest
    # scripts) can capture per-turn token costs without re-reading the DB.
    # API SSE layer filters this event out before forwarding to clients.
    yield UsageSummary(tokens_in=usage.input_tokens, tokens_out=usage.output_tokens)

    # ── ⑦ 执行所有 XML 标签的状态变更副作用 ──────────────────────────────────
    # apply_tags 是"状态机"：遍历 completed_tags，每种标签触发对应的 DB 更新：
    #   <state_change hp="-5"/>    → 更新 CharState.stats_json 里的 hp
    #   <npc_update name="X" favor="+10"/> → 更新 NPC.favor
    #   <location_enter name="客栈"/> → 更新 Location.is_current
    #   <plot_event type="discovery"/> → 创建 PlotThread 记录
    #   … 等约 20 种标签各有自己的处理逻辑
    await apply_tags(
        session,
        session_id,
        next_turn,
        completed_tags,
    )

    # v0.15 — auto-trigger framework events whose structured predicates
    # are now satisfied. Inert for legacy free-text predicates.
    if sess.framework_id:
        from dzmm.service.event_evaluator import check_and_trigger_events
        await check_and_trigger_events(session, session_id, next_turn)

    # 软校验：检查本回合是否有 NPC 在非预期地点出场（可能是 GM 忘记铺垫遭遇）
    # 只记录警告，不中断游戏（"软"校验的含义）
    from dzmm.service.encounter_check import check_encounter_warnings
    await check_encounter_warnings(
        session, session_id, completed_tags, current_turn=next_turn,
    )

    # 更新场景回合计数器（检测 PC 是否在同一地点停留太久）
    _update_scene_turn_count(sess, completed_tags)

    # ── ⑨ 更新会话状态 ────────────────────────────────────────────────────────
    sess.turn_count = next_turn
    sess.last_played = datetime.now(UTC).replace(tzinfo=None)  # 记录最后游玩时间

    # ── ⑩ NPC 主动联系检查 ────────────────────────────────────────────────────
    # 本回合结束后，检查是否有 NPC 满足"主动联系"条件（如好感度高、触发事件等）
    # 如果有，yield 一个 npc_initiative 事件，前端收到后自动调用 /npc_tick 接口
    # 这样 NPC 就会在下一回合开始前主动给 PC 发消息，不需要玩家先行动
    initiative_npc = await find_initiative_npc(session, session_id, next_turn)
    if initiative_npc is not None:
        initiative_npc.last_initiative_turn = next_turn  # 记录上次主动联系的回合，避免重复
        yield TagComplete(
            name="npc_initiative",
            attrs={"npc": initiative_npc.name},
            content="",
        )
        log.info(
            "npc_initiative scheduled: %s (turn %d)", initiative_npc.name, next_turn
        )


# _extract_pc_hooks：从角色卡 Markdown 文本中提取"能力/物品/弱点"三类钩子信息
# 这些信息会在每回合注入 GM Prompt 的 "PC 钩子（用上它们）" 部分，
# 提醒 GM 让这些角色特质在叙事中发挥作用（而不是每回合都忽视角色的特殊能力）
#
# 提取策略：启发式（heuristic）扫描，不需要格式完全标准化：
#   - 支持 Markdown 标题（## 能力）
#   - 支持粗体标注（**技能**）
#   - 支持"键: 值"格式（物品: 魔法匕首, 解毒剂）
def _extract_pc_hooks(profile_md: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"abilities": [], "items": [], "weaknesses": []}
    if not profile_md:
        return out
    # 每个类别对应一个正则关键词，用 | 隔开的是同义词（能力/技能/绝技/擅长/专精 都算"能力"）
    section_pat = {
        "abilities": r"(?:能力|技能|绝技|擅长|专精)",
        "items": r"(?:物品|装备|道具|随身|身上)",
        "weaknesses": r"(?:弱点|弱项|禁忌|忌讳|害怕|畏惧)",
    }
    for key, kw in section_pat.items():
        # rf"..." 是 f-string + raw string 的组合
        # (?:^#+\s*{kw}...) 匹配三种格式：Markdown标题 / **粗体** / 键: 值
        # re.M 让 ^ 匹配每行的行首（不只是整个字符串的开头）
        m = re.search(
            rf"(?:^#+\s*{kw}|\*\*\s*{kw}\s*\*\*|{kw}[:：])",
            profile_md,
            re.M,
        )
        if not m:
            continue  # 这个类别在 profile 中找不到，跳过
        # m.end()：匹配到的字符串的结束位置，截取这个位置之后的文本
        rest = profile_md[m.end():]
        # 找下一个标题的位置（用于确定当前节的结束边界）
        next_heading = re.search(
            r"^#+\s|\*\*\s*[一-鿿]{2,4}\s*\*\*", rest, re.M
        )
        block = rest[: next_heading.start()] if next_heading else rest  # 截取当前节的文本
        # 先尝试提取 Markdown 列表项（- 或 • 或 * 开头的行）
        items = re.findall(r"[-•*]\s*(.+?)(?:$|\n)", block)
        if not items:
            # 列表提取失败：按逗号/顿号/分号分割（逗号分隔的内联格式）
            items = [
                s.strip()
                for s in re.split(r"[,，、；;]", block.strip())
                if s.strip()
            ][:6]  # 切片 [:6] 最多取前 6 项
        # 每项截断到 50 字符，最多取 6 条——保持 key_facts 简洁，不占用太多 token
        out[key] = [it.strip()[:50] for it in items if it.strip()][:6]
    return out


_CHARACTER_MD_BUDGET = 1200  # 角色卡的最大字符数预算（约 600-800 个 token）


# _truncate_character_md：截断过长的角色卡文本，只保留最重要的部分
#
# 为什么要截断？
# AI 助手生成的角色卡（"角色生成器"）可能有 3000-5000 字的详细背景故事
# 把整个文本放入 GM Prompt 会：
#   1. 消耗过多 token（降低成本和速度）
#   2. 让 LLM 关注冗长背景而忽视关键的钩子信息
# 解决方案：只保留前 1200 字（基本信息 + 前几节），删掉后面的背景故事散文
# 关键钩子（能力/物品/弱点）已经由 _extract_pc_hooks 单独提取，不会丢失
#
# 截断策略（优先保持 Markdown 结构完整性）：
#   1. 如果文本 ≤ 1200 字：原样返回
#   2. 找到 1200 字之内最后一个 Markdown 标题（## 或 #），在那里截断
#   3. 找不到合适的标题边界：直接硬截断 + 省略号提示
def _truncate_character_md(profile: str, budget: int = _CHARACTER_MD_BUDGET) -> str:
    if len(profile) <= budget:
        return profile  # 文本未超预算：原样返回
    # 截取前 budget 个字符
    head = profile[:budget]
    # rfind()：从右向左找第一个匹配项，返回位置（找不到返回 -1）
    # max() 取两个位置的较大值（即更靠后的那个标题边界）
    cut = max(head.rfind("\n## "), head.rfind("\n# "))
    if cut > budget // 2:  # 只在"后半段"找到边界才使用（避免在开头就截断）
        return profile[:cut].rstrip() + "\n\n（…后续详细背景已省略，详细钩子见 key_facts）"
    # 没找到合适的标题边界：硬截断
    return profile[:budget].rstrip() + "…\n\n（…profile 已截断，详细钩子见 key_facts）"


_GENDER_CN = {"male": "男", "female": "女"}


# _format_character_card：把角色对象格式化成给 GM 看的文本卡片
# 在角色卡顶部加上等级和性别信息——这两项对 GM 叙事很重要：
#   - 等级影响 NPC 对 PC 的态度（低等级时 NPC 可能轻视 PC）
#   - 性别影响部分 NPC 的反应方式和称谓
# 长角色卡会被截断（调用 _truncate_character_md），避免占用太多 token
def _format_character_card(char: Character) -> str:
    profile = (char.profile_md or "").strip()
    level_line = f"等级: Lv {char.level}"   # char.level 是整数（如 5）
    header_lines = [level_line]
    # 只在 gender 有值且是已知性别时添加（None 或 unknown 时不添加性别行）
    if (char.gender or "") in _GENDER_CN:
        header_lines.append(f"性别: {_GENDER_CN[char.gender]}")
    header = "\n".join(header_lines)  # 把头部行列表拼成字符串
    if profile:
        profile = _truncate_character_md(profile)    # 截断过长的角色卡
        return f"{header}\n\n{profile}"   # 头部 + 空行 + 角色卡正文
    return header  # 没有 profile 的角色（如仅有基础信息的新角色）只返回头部


# _build_live_state：合并"基础属性"和"动态状态"成一个字典
# 两级设计的原因：
#   - Character.base_stats_json：角色创建时的固定基础属性（力量/敏捷/等级等）
#   - CharState.stats_json：会随游戏变化的动态属性（hp/san 等可变数值）
#   - CharState.inventory_json：背包物品列表（同样动态变化）
# 合并后返回的字典里所有属性都在一起，方便后续使用
def _build_live_state(char: Character, cs: CharState | None) -> dict:
    if cs is None:
        # 没有动态状态记录（新开局还没产生过 state_change）：直接返回基础属性
        return json.loads(char.base_stats_json or "{}")
    out = json.loads(cs.stats_json or "{}")  # 先加载动态属性
    out["inventory"] = json.loads(cs.inventory_json or "[]")  # 再加入背包
    return out  # 动态属性覆盖同名基础属性（正确的语义：动态属性是最新状态）


# _load_recent_messages：加载"摘要点之后"的最近 N 条历史消息
# 这些消息以 {role, content} 格式传入 LLM——让 LLM 知道最近几回合发生了什么
#
# 关键逻辑：high_water（高水位线）
#   摘要器每运行一次，会记录"已摘要到哪条消息 ID"（last_summarized_msg_id）
#   加载历史时只取 ID > high_water 的消息（摘要之后的部分）
#   摘要之前的内容已经被 story_summary 文字摘要覆盖，不需要再放入消息列表
async def _load_recent_messages(
    session: AsyncSession,
    session_id: int,
    summary_row: StorySummary | None,  # 可能为 None（从未运行过摘要器）
) -> list[Message]:
    sess = await session.get(GameSession, session_id)
    turn_count = sess.turn_count if sess is not None else 0
    window = _recent_window_for(turn_count)  # 根据游戏进度决定加载多少条

    # high_water = 0 时（没有摘要），会加载全部消息中最新的 window 条
    high_water = summary_row.last_summarized_msg_id if summary_row else 0
    rows = (
        await session.execute(
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .where(MessageRow.id > high_water)  # 只取摘要点之后的消息
            .order_by(MessageRow.id.desc())      # 从最新到最旧排序（便于 LIMIT）
            .limit(window)                       # 只取最新的 window 条
        )
    ).scalars().all()
    rows = list(reversed(rows))  # 反转回"从旧到新"的顺序（LLM 需要按时间顺序的对话历史）
    # 把 MessageRow ORM 对象转换成 Message 模型对象（只保留 role 和 content）
    return [Message(role=r.role, content=r.content) for r in rows]


# NPC 档案格式化器（v0.1.6 重构后移到子模块，这里重新导出以保持向后兼容）
# _format_npc_dossier：完整的 NPC 档案（姓名/性格/好感度/记忆/当前情绪等）
# _format_npc_short：简短的 NPC 单行摘要（用于"其他 NPC"列表，节省 token）
# _npc_revealed：判断 NPC 信息是否应该显示给 GM（隐藏 NPC 可能还没被揭示）
from dzmm.service.npc_dossier import (
    _format_npc_dossier,
    _format_npc_short,
    _npc_revealed,
)


# _detect_combat_recent：检测当前是否处于战斗状态（最近 5 回合内有未关闭的战斗）
# 用途：决定是否在 GM Prompt 里注入战斗相关的标签文档
# 实现：扫描最近 5 回合的 events_json，统计 combat_start 和 combat_end 的差值
# 如果 combat_start > combat_end（还有未关闭的战斗），或者最近有 combat_start，返回 True
async def _detect_combat_recent(
    session: AsyncSession, session_id: int, current_turn: int
) -> bool:
    if current_turn < 1:
        return False  # 第 0 回合还没有历史，不可能有战斗
    # 只查 events_json 列（不加载整条消息），节省内存和传输量
    rows = (await session.execute(
        select(MessageRow.events_json)
        .where(
            MessageRow.session_id == session_id,
            MessageRow.role == "assistant",
            # max(1, ...) 防止 current_turn 为 0 时减出负数
            MessageRow.turn >= max(1, current_turn - 5),
        )
        .order_by(MessageRow.turn.asc(), MessageRow.id.asc())  # 按时间顺序排
    )).scalars().all()
    open_combats = 0  # "战斗嵌套计数器"（通常不超过 1，但理论上可以嵌套）
    for raw in rows:
        if not raw:
            continue
        try:
            evs = json.loads(raw)  # events_json 是 JSON 数组字符串
        except (TypeError, ValueError):
            continue  # 解析失败（损坏的数据）：跳过这条消息
        if not isinstance(evs, list):
            continue
        for ev in evs:
            if not isinstance(ev, dict):
                continue
            t = ev.get("type")
            if t == "combat_start":
                open_combats += 1   # 战斗开始：计数+1
            elif t == "combat_end" and open_combats > 0:
                open_combats -= 1   # 战斗结束：计数-1（保证不会变成负数）
    # 有未关闭的战斗：需要注入战斗文档
    if open_combats > 0:
        return True
    # 即使战斗已关闭，最近 5 回合内也有战斗：仍然注入（GM 可能重新触发战斗）
    for raw in rows:
        if raw and "combat_start" in raw:
            return True
    return False  # 最近 5 回合没有任何战斗事件


# _render_event：把剧本事件对象渲染成 GM 可读的文本
# 兼容两种格式：
#   旧版本（legacy）：直接是字符串（如"PC 找到神秘钥匙"）
#   新版本（v0.9+）：字典格式，含描述、关键词、完成标准（更结构化）
def _render_event(ev: "str | dict") -> str:
    if isinstance(ev, str):
        return ev  # 旧格式：直接返回字符串
    # 新格式：从字典提取各字段，拼成多行文本
    desc = ev.get("description", "")
    keywords = ev.get("keywords") or []  # or [] 处理 None 值（字段可能缺失）
    criteria = ev.get("criteria", "")
    parts = [desc]
    if keywords:
        # "／".join(...)：用全角斜杠连接关键词列表（中文文档惯用格式）
        parts.append(f"  关键词：{'／'.join(str(k) for k in keywords)}")
    if criteria:
        parts.append(f"  完成标准：{criteria}")
    return "\n".join(parts)  # 用换行符把各部分拼成一段


# ══════════════════════════════════════════════════════════════════════════════
# _build_key_facts：构建 GM Prompt 里的"当前游戏状态"文本块
# ══════════════════════════════════════════════════════════════════════════════
#
# 这是 Prompt 工程的核心函数：把数据库里的游戏状态翻译成 LLM 能理解的 Markdown 文本。
# 函数输出被称为 "key_facts"（关键事实），注入到 GM Prompt 的 system message 里。
#
# 函数按以下顺序构建内容：
#   1. 当前回合编号（防止 GM 忘记回合数）
#   2. PC 身份锁定（防止 GM 把 PC 改名）
#   3. 当前世界时间（天/时段/天气）
#   4. NPC 列表（3-pass 策略，见下方）
#   5. NPC 长期记忆（只注入与当前行动相关的片段）
#   6. 进行中的剧情线
#   7. PC 当前目标
#   8. 当前地点 + 周边拓扑
#   9. 场景节奏压力（停留太久时强制推进）
#   10. PC 心情
#   11. NPC 关系图
#   12. 剧本进度（当前章节/主线事件/支线事件）
#   13. 剧本强推（主线卡太久时强制推进）
#   14. 隐藏事件（GM only 的暗中状态）
#   15. 派系关系
#   16. PC 钩子（能力/物品/弱点）
#   17. PC 当前数值（属性/等级/背包）
#   18. 骰子监控（检测 LLM 是否反复输出同一骰子值）
#   19. 本回合要点（动态 GM 指令）
#
# 【NPC 3-pass 策略】
#   Pinned NPC（被标记为重点关注的 NPC）：全部加载，显示完整档案
#   Recently-seen NPC（最近出场的其他 NPC）：加载前 8 个，显示简短信息
#   Recalled NPC（本回合被"召回"的 NPC）：全部加载，显示完整档案
#   这样在 token 限制内最大化 NPC 上下文：重点 NPC 详细，次要 NPC 简洁
#
async def _build_key_facts(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    character: Character | None = None,   # PC 角色对象（None 表示没有角色的特殊情况）
    ollama_base_url: str | None = None,   # 本地 Ollama 地址，用于 NPC 记忆 RAG 检索
    user_action: str = "",                # 玩家本回合行动（用作 RAG 查询词）
) -> str:
    # ── Pass 1: 加载 Pinned NPC（被重点标注的 NPC）──────────────────────────
    # NPC.pinned = True 意味着这个 NPC 是当前剧情的核心人物（玩家关注/GM 标记）
    # 按最近出场回合排序（最近出场的排前面）
    # noqa: E712 是告诉 linter 忽略"应该用 is True"的警告（SQLAlchemy 的 == True 是有效语法）
    pinned_npcs = (
        await session.execute(
            select(NPC)
            .where(NPC.session_id == session_id, NPC.pinned == True)  # noqa: E712
            .order_by(NPC.last_seen_turn.desc())
        )
    ).scalars().all()
    pinned_ids = {n.id for n in pinned_npcs}  # 集合推导式：快速 O(1) 查找用

    # ── Pass 2: 加载最近出场的其他 NPC（排除已 pinned 的）────────────────────
    # 先加载前 16 条（避免重复过滤后不足 8 条），然后手动排除 pinned NPC
    recent_npcs = (
        await session.execute(
            select(NPC)
            .where(NPC.session_id == session_id)
            .order_by(NPC.last_seen_turn.desc())
            .limit(16)  # 多加载一些，过滤后能保证有足够的备选
        )
    ).scalars().all()
    recent_filtered: list[NPC] = []
    for n in recent_npcs:
        if n.id in pinned_ids:
            continue         # 跳过已经在 pinned 列表里的 NPC（避免重复）
        recent_filtered.append(n)
        if len(recent_filtered) >= 8:
            break  # 够 8 个了，停止

    sess = await session.get(GameSession, session_id)
    # ── Pass 3: 处理"召回"NPC（本回合一次性注入全量档案）────────────────────
    # recall_pending_json 是一个 NPC 名字列表，由某些触发器（如查看记忆/重要剧情）填入
    # 本回合消费（drain）后清空——所以是"one-shot"（一次性）机制
    recalled_names: list[str] = []
    if sess is not None:
        try:
            raw = json.loads(sess.recall_pending_json or "[]")
            if isinstance(raw, list):
                recalled_names = [str(x) for x in raw if x]
        except (TypeError, ValueError):
            recalled_names = []
        # drain：消费后清空，下回合不会再次注入
        if recalled_names:
            sess.recall_pending_json = "[]"

    recalled_npcs: list[NPC] = []
    seen_ids = pinned_ids | {n.id for n in recent_filtered}  # | 是集合并集运算符
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

    # 加载进行中的剧情线（PlotThread）：按重要度排序，最多 8 条
    # 剧情线由 <plot_event> 标签触发创建，是 GM 叙事的"副线任务"框架
    threads = (
        await session.execute(
            select(PlotThread)
            .where(PlotThread.session_id == session_id, PlotThread.status == "active")
            .order_by(PlotThread.importance.desc(), PlotThread.id.desc())  # 重要的排前面
            .limit(8)
        )
    ).scalars().all()

    # ── 开始组装 key_facts 文本 ──────────────────────────────────────────────
    # parts 列表：每个元素是 key_facts 的一个"块"，最后用 \n 拼成完整字符串
    # 第一条：当前回合编号（防止 LLM 在摘要窗口压缩后忘记现在是哪个回合）
    parts: list[str] = [f"**当前是第 {current_turn} 回合**"]

    # PC 身份锁：最高优先级，防止 GM 改变 PC 的名字
    # 这个 bug 在 v0.9 中实测出现（游戏第 3 回合后 GM 开始叫 PC 别的名字）
    # 通过在每回合的 key_facts 最顶部重申 PC 名字来修复
    if character is not None:
        identity_lines = [
            "## PC 身份（最高优先级，永不可改）",
            f"姓名: {character.name}",
        ]
        profile = (character.profile_md or "").strip()
        if profile:
            # 只取 profile 的前 80 字符（去掉换行符变成单行），避免身份块占用太多 token
            snippet = profile.replace("\n", " ").strip()[:80]
            if snippet:
                identity_lines.append(f"身份: {snippet}")
        identity_lines.append(
            "无论后文如何，PC 的姓名必须始终是上面这个，不得改名、不得替换、不得简称为别的名字。"
        )
        parts.append("\n".join(identity_lines))

    # 世界时间：注入当前游戏内时间（如"第 3 天 · 深夜 · 小雨"）
    # GM 用这个信息决定什么时候推进时间轴，叙事中自然引用天气/时段
    if sess is not None:
        wt_str = format_world_time_cn(sess.world_time_json)
        if wt_str:
            parts.append(f"\n## 当前时间\n{wt_str}")

    # 注入 Pinned NPC 完整档案（含好感度/情绪/记忆/当前位置等）
    if pinned_npcs:
        parts.append("📌 重点 NPC（始终在场或玩家关注）：")
        for n in pinned_npcs:
            parts.append(_format_npc_dossier(n))  # 每个 NPC 一个详细文本块

    # NPC 长期记忆 RAG 检索：用当前玩家行动作为查询词，
    # 检索每个 Pinned NPC 历史上说过的最相关的话，注入 GM Prompt
    # 这样 NPC 的行为会和之前说过的内容保持一致（"你上次说要帮我的"）
    # 只检索前 4 个 pinned NPC（避免过多 RAG 调用）
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
                        parts.append(f"- {m}")  # 每条相关记忆一行
            except Exception:  # noqa: BLE001
                pass  # 记忆检索失败不影响游戏（非致命）

    # 注入"最近出现的其他 NPC"简短列表
    # 用 _format_npc_short 而不是 _format_npc_dossier 节省 token
    if recent_filtered:
        parts.append("\nNPC 列表：" if not pinned_npcs else "\n最近出现的其他 NPC：")
        for n in recent_filtered:
            parts.append(_format_npc_short(n))

    # 注入本回合"召回"的 NPC 完整档案（one-shot，下回合不再注入）
    if recalled_npcs:
        parts.append("\n🔁 本回合回归的 NPC（请重新带入设定）：")
        for n in recalled_npcs:
            parts.append(_format_npc_dossier(n))

    # 注入进行中的剧情线（按重要度显示，★★★ = 最重要）
    if threads:
        parts.append("\n进行中的剧情线：")
        for t in threads:
            stars = "★" * t.importance  # "★" * 3 = "★★★"（字符串重复运算符）
            parts.append(f"- [{t.type} {stars}] {t.description}")

    # 注入 PC 的活跃目标（任务清单），按优先级排序
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
            # 字典.get(key, default)：查找优先级对应的星标，找不到用默认值 ★★
            prio_mark = {"high": "★★★", "normal": "★★", "low": "★"}.get(g.priority, "★★")
            parts.append(f"- [id={g.id}] {prio_mark} {g.description}")

    # ── 当前地点 + 周边拓扑 ───────────────────────────────────────────────────
    # 从数据库查询 is_current=True 的地点（每个 session 同一时刻只有一个当前地点）
    current_loc = (
        await session.execute(
            select(Location).where(
                Location.session_id == session_id,
                Location.is_current == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if current_loc is None:
        # 实测 bug：GM 可能叙事了 17 回合但从未 emit <location_enter>
        # 导致前端侧边栏"当前场所"一直空白，场景节奏压力也无法触发
        # 解决：检测到没有地点时，强制要求 GM 本回合必须 emit location_enter
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

        # 把三类 NPC 列表合并，筛选出"当前位置"等于当前地点的 NPC
        # lower() 大小写不敏感比较（"客栈" == "客栈" 但也处理 "Tavern" == "tavern"）
        all_collected_npcs = list(pinned_npcs) + list(recent_filtered) + list(recalled_npcs)
        scene_npcs = [
            n for n in all_collected_npcs
            if (n.current_location or "").lower() == current_loc.name.lower()
        ]
        if scene_npcs:
            # "、".join(...) 用中文顿号连接 NPC 名字列表（生成器表达式 n.name for n in scene_npcs）
            loc_lines.append("在场 NPC：" + "、".join(n.name for n in scene_npcs))
        else:
            loc_lines.append("在场 NPC：无")

        # 地点物品列表（从 items_json 解析）
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
                # 有描述时加括号：如"魔法匕首（+2攻击）"，没有描述只显示名字
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
        # v0.15.1 D2 — 若有 framework_id，加载 WorldLocation.connections_json
        # 用来在拓扑行里附加"路程 N 回合"信息，让 GM 感知距离远近。
        # 结构：{peer_name -> travel_turns}（仅当 framework_id 存在时有效）
        world_travel_map: dict[str, int] = {}
        if sess is not None and sess.framework_id:
            try:
                # 找到与当前 Location 同名的 WorldLocation（在相同 framework 下）
                wl_row = (await session.execute(
                    select(WorldLocation).where(
                        WorldLocation.framework_id == sess.framework_id,
                        WorldLocation.name == current_loc.name,
                    )
                )).scalar_one_or_none()
                if wl_row is not None:
                    raw_conns = json.loads(wl_row.connections_json or "[]")
                    if isinstance(raw_conns, list):
                        # 先建 target_id → WorldLocation 名字的映射
                        target_ids = [
                            c.get("target_id") for c in raw_conns
                            if isinstance(c, dict) and isinstance(c.get("target_id"), int)
                        ]
                        if target_ids:
                            peer_wl_rows = (await session.execute(
                                select(WorldLocation).where(
                                    WorldLocation.id.in_(target_ids)
                                )
                            )).scalars().all()
                            id_to_name = {r.id: r.name for r in peer_wl_rows}
                            for c in raw_conns:
                                if not isinstance(c, dict):
                                    continue
                                tid = c.get("target_id")
                                tt = c.get("travel_turns")
                                if isinstance(tid, int) and isinstance(tt, int) and tid in id_to_name:
                                    world_travel_map[id_to_name[tid]] = tt
            except Exception:  # noqa: BLE001
                pass  # 防御：JSON 解析失败或数据库异常时静默跳过

        topo_lines: list[str] = []
        seen_peer_names: set[str] = set()
        for e, peer in edges_out:
            suffix = f"（{e.description}）" if e.description else ""
            tt = world_travel_map.get(peer.name)
            if tt is not None:
                suffix += f"（路程 {tt} 回合）"
            topo_lines.append(f"- 此处 {e.relation} → {peer.name}" + suffix)
            seen_peer_names.add(peer.name)
        for e, peer in edges_in:
            suffix = f"（{e.description}）" if e.description else ""
            tt = world_travel_map.get(peer.name)
            if tt is not None:
                suffix += f"（路程 {tt} 回合）"
            topo_lines.append(f"- {peer.name} {e.relation} → 此处" + suffix)
            seen_peer_names.add(peer.name)

        # framework 会话：对于尚未在 LocationEdge 中登记的 WorldLocation 邻居，
        # 也渲染出来（开放世界早期阶段 GM 可能还没 emit location_edge）
        if sess is not None and sess.framework_id and world_travel_map:
            for peer_name, tt in world_travel_map.items():
                if peer_name not in seen_peer_names:
                    topo_lines.append(
                        f"- （预设）→ {peer_name}（路程 {tt} 回合，尚未确认进入）"
                    )

        if topo_lines:
            parts.append(
                "\n## 周边拓扑（已确认，禁止违背）\n" + "\n".join(topo_lines)
                + "\n（PC 离开此处只能去**与此处直接相连**的地点；"
                "进入新地点必须先 emit `<location_edge>` 把空间关系锁住。）"
            )

    # 地点拓扑越界警告：上回合的 _apply_location_enter 检测到"从 A 跳到 B 但没 emit edge"
    # 把警告写入 topology_warning_json，本回合读取后消费（drain）并展示给 GM
    # 目的：让 GM 补发缺失的 <location_edge> 标签，保持世界地图拓扑完整性
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
                + "\n".join(f"- {w}" for w in warnings)  # 生成器表达式格式化每条警告
            )
            sess.topology_warning_json = "[]"  # drain：清空警告，只提示一次

    # 场景节奏压力：根据 scene_turn_count 注入不同强度的推进指令
    # stc >= SCENE_HARD_EXIT_TURNS（7）：强制必须离开当前地点
    # stc >= SCENE_SOFT_PRESSURE_TURNS（4）：软性提示需要推进
    # 这解决了 GM 在同一地点无限拖延的问题（实测 20 回合困在同一酒馆）
    if current_loc is not None and sess is not None:
        stc = sess.scene_turn_count or 0  # or 0：防止 None 导致比较出错
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

    # PC 心情：注入 PC 当前情绪状态（由 <state_change mood="恐惧+3"> 等标签更新）
    # GM 根据这个状态调整叙事语气和 NPC 的回应方式
    # sorted() + key=lambda：按心情值从大到小排序，取前 5 个最强烈的情绪
    if sess is not None:
        try:
            moods = json.loads(sess.pc_mood_json or "{}")
        except (TypeError, ValueError):
            moods = {}
        if isinstance(moods, dict) and moods:
            sorted_moods = sorted(
                # 生成器表达式：把 {情绪: 值} 字典转成 (情绪, 值) 元组列表
                ((str(k), int(v)) for k, v in moods.items() if isinstance(v, (int, float))),
                key=lambda x: -x[1],  # lambda 匿名函数：以值的负数排序（从大到小）
            )[:5]
            if sorted_moods:
                parts.append("\nPC 当前心情：")
                # 用 " / " 连接所有情绪，格式如"恐惧(8) / 悲伤(5) / 愤怒(3)"
                parts.append("- " + " / ".join(f"{k}({v})" for k, v in sorted_moods))

    # NPC 之间的关系：让 GM 知道哪些 NPC 互相认识、关系如何（否则 GM 可能自相矛盾）
    relations = (
        await session.execute(
            select(NpcRelation)
            .where(NpcRelation.session_id == session_id)
            .order_by(NpcRelation.introduced_turn.desc(), NpcRelation.id.desc())
            .limit(10)  # 最多 10 条，避免占用太多 token
        )
    ).scalars().all()
    if relations:
        parts.append("\nNPC 关系：")
        for r in relations:
            parts.append(f"- {r.npc_a} ↔ {r.npc_b} [{r.kind}]")

    # ── 剧本进度 ───────────────────────────────────────────────────────────────
    # 查询最新版本（version DESC）的激活剧本（如果有多版本，取最新的）
    # 没有剧本的 Legacy 会话（无 Screenplay 行）直接跳过整个块
    sp = (
        await session.execute(
            select(Screenplay)
            .where(
                Screenplay.session_id == session_id,
                Screenplay.status == "active",
            )
            .order_by(Screenplay.version.desc())
        )
    ).scalars().first()  # .first()：只取第一行（最新版本），没有则返回 None
    if sp is not None:
        # 解析 JSON 字段：try/except 防止损坏的 JSON 导致整个函数崩溃
        try:
            chapters = json.loads(sp.chapters_json or "[]")
        except (TypeError, ValueError):
            chapters = []
        if not isinstance(chapters, list):
            chapters = []
        try:
            completed = json.loads(sp.completed_events_json or "[]")  # 已完成事件的列表
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

                        # v0.15.1 C4+ — 8-turn stall: auto-complete the first
                        # pending main event directly in the DB so the GM doesn't
                        # have to. This fires ONCE per stall episode (the auto
                        # entry carries turn=current_turn so next build will see
                        # turns_since_progress ≈ 0 and stop firing).
                        if turns_since_progress >= 8:
                            try:
                                auto_entry = {
                                    "chapter": sp.current_chapter,
                                    "event_idx": next_idx,
                                    "type": "main",
                                    "turn": current_turn,
                                    "auto": True,
                                }
                                completed_updated = list(completed)
                                completed_updated.append(auto_entry)
                                sp.completed_events_json = json.dumps(
                                    completed_updated, ensure_ascii=False
                                )
                                log.info(
                                    "stall_auto_advance session=%s turn=%s "
                                    "chapter=%s event_idx=%s",
                                    session_id,
                                    current_turn,
                                    sp.current_chapter,
                                    next_idx,
                                )
                                event_desc = _render_event(next_event)
                                parts.append(
                                    f"## ❗ 系统自动推进（8 回合无进度）\n"
                                    f"已自动完成主线事件：本章事件 #{next_idx + 1}"
                                    f"「{event_desc}」\n"
                                    f"原因：剧情长时间停滞，系统帮 GM 推进。\n"
                                    f"本回合 GM 必须叙述该事件如何在故事中发生"
                                    f"（不必精确，但必须呈现结果）。"
                                )
                            except Exception:  # noqa: BLE001
                                # 防御：任何失败（Screenplay 不存在、JSON 损坏等）
                                # 回退到普通强推警告
                                urgency = "❗❗ 极度紧急"
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
                        else:
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

    # ── 隐藏事件（GM-only 暗中状态）──────────────────────────────────────────
    # HiddenEvent 是 GM 私有的"倒计时炸弹"：玩家看不到，但 GM 每回合都会收到提醒
    # 典型例子：PC 被毒了（中毒计时器）、NPC 在秘密谋划（阴谋倒计时）、某个秘密即将曝光
    # "Re-inject every turn"：每回合重新注入（而不是只在创建时注入一次），
    # 确保 GM 始终记得这些背景约束，不会"忘记" PC 还在流血
    hidden = (
        await session.execute(
            select(HiddenEvent)
            .where(
                HiddenEvent.session_id == session_id,
                HiddenEvent.status == "active",
            )
            .order_by(HiddenEvent.introduced_turn)  # 按创建回合排序，老的在前
        )
    ).scalars().all()
    if hidden:
        lines = ["\n## 暗中状态(GM only)"]
        for ev in hidden:
            age = current_turn - ev.introduced_turn  # 该事件已存在多少回合
            sub = (ev.subject or "").strip() or "?"  # 事件主体（如"PC"或"黑幕势力"）
            kind = (ev.kind or "").strip()            # 事件类型（如"中毒"/"秘密计划"）
            desc = (ev.description or "").strip()     # 事件描述
            cons = (ev.consequence or "").strip()     # 如果不处理会有什么后果
            tail = desc
            if cons:
                tail = f"{tail}。{cons}" if tail else cons  # 合并描述和后果
            # 格式：[主体·类型·已过t回合] 描述。后果
            lines.append(f"- [{sub}·{kind}·t+{age}] {tail}")
        parts.append("\n".join(lines))

    # ── 势力关系 ───────────────────────────────────────────────────────────────
    # 把 PC 在各派系中的声望值格式化给 GM
    # rep >= 30：盟友（NPC 更信任 PC，愿意提供帮助）
    # rep <= -30：敌人（NPC 警惕/敌视 PC，甚至可能主动攻击）
    # 中间：中立（正常互动）
    factions = (await session.execute(
        select(Faction).where(Faction.session_id == session_id)
    )).scalars().all()
    if factions:
        facts_lines = ["\n## 势力关系（PC 在各派系中的口碑）"]
        for f in factions:
            # 三元表达式嵌套：先判断盟友，再判断敌人，否则是中立
            rep_label = "盟友" if f.pc_reputation >= 30 else ("敌人" if f.pc_reputation <= -30 else "中立")
            line = f"- {f.name}（{rep_label}, rep={f.pc_reputation}）"
            if f.ideology:
                line += f"：{f.ideology}"  # 显示派系理念（可选字段）
            facts_lines.append(line)
        parts.append("\n".join(facts_lines))

    # ── PC 钩子（提醒 GM 使用角色特质）───────────────────────────────────────
    # 很多 GM 会忘记 PC 有哪些特殊能力/物品/弱点，导致这些角色特质形同虚设
    # 把它们显式列在每回合的 key_facts 里，强制让 GM 在叙事中调用它们
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

    # ── PC 当前数值（属性/等级/背包）──────────────────────────────────────────
    # 注意：hp 和 sanity 已经在 live_state 中显示，这里排除它们（避免重复）
    # 其他数值属性（力量/魅力/技能等）显示在这里，供 GM 设置骰子 DC 时参考
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
        # 列表推导式：过滤出数值型属性，排除 hp/max_hp/sanity/max_sanity（已在面板显示）
        attr_pairs = [
            (k, v)
            for k, v in stats.items()
            if isinstance(v, (int, float))
            and k not in ("hp", "max_hp", "sanity", "max_sanity")
        ]
        level = character.level or 1  # or 1：level 为 None 时默认 1 级
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
                # 把属性列表格式化成 "力量=8 / 敏捷=12 / ..." 的形式
                attr_str = " / ".join(f"{k}={v}" for k, v in attr_pairs)
                num_lines.append(f"属性: {attr_str}")
            if inventory:
                # inventory[:8]：最多显示前 8 件物品，避免物品太多占满 token
                inv_str = "、".join(str(it) for it in inventory[:8])
                num_lines.append(f"物品: {inv_str}")
            num_lines.append(
                "（dice 检定的 DC 应基于属性合理设置；物品要在 narrative 显式引用；等级影响 NPC 态度。）"
            )
            parts.append("\n".join(num_lines))

    # ── 骰子监控（检测 LLM 是否反复输出同一个骰子值）────────────────────────
    # 实测 bug：某个本地模型在 72 回合中有 8 回合连续输出 d20=9，
    # 这是 LLM "锁定"了一个常数的典型特征（模型过度拟合某个模式）
    # 解决：检测到连续相同值时，在 GM Prompt 里注入警告让它用服务端预掷值
    recent_msgs = (
        await session.execute(
            select(MessageRow)
            .where(
                MessageRow.session_id == session_id,
                MessageRow.role == "assistant",
            )
            .order_by(MessageRow.id.desc())
            .limit(5)  # 只看最近 5 条消息就足够了
        )
    ).scalars().all()
    recent_msgs = list(reversed(recent_msgs))  # 反转回时间顺序
    d20_values = extract_d20_values_from_messages(recent_msgs)  # 提取历史骰子值列表
    stuck = detect_stuck_dice(d20_values, min_streak=2)  # 检测是否有连续重复值（≥2 次相同）
    if stuck is not None:
        parts.append(build_stuck_warning(d20_values, stuck))  # 注入骰子固化警告

    # ── v0.15 Batch 2: 上回合机械结算（pending_resolutions_json） ────────────
    # 注入上回合 Python 引擎执行的骰子/技能/物品结算结果，供 GM 叙事时引用。
    # 只注入 turn == current_turn - 1 的记录（"刚刚结算的"），最多 5 条。
    # 注入后不清空（drain），由调用方或更新逻辑决定何时丢弃旧记录。
    if sess is not None:
        try:
            pending_raw = json.loads(sess.pending_resolutions_json or "[]")
            if not isinstance(pending_raw, list):
                pending_raw = []
        except (TypeError, ValueError):
            pending_raw = []

        last_turn = current_turn - 1
        # Filter to entries from the immediately-preceding turn
        prev_resolutions = [
            r for r in pending_raw
            if isinstance(r, dict) and r.get("turn") == last_turn
        ]
        # Cap at 5 to avoid prompt bloat
        prev_resolutions = prev_resolutions[-5:]

        if prev_resolutions:
            res_lines = ["\n## 上回合机械结算"]
            for rec in prev_resolutions:
                kind = rec.get("kind", "")
                inp = rec.get("input") or {}
                res = rec.get("result") or {}

                if kind == "dice":
                    formula = inp.get("formula", "?")
                    purpose = res.get("purpose") or inp.get("purpose", "骰点")
                    rolls = res.get("rolls", [])
                    modifier = res.get("modifier", 0)
                    total = res.get("total", 0)
                    rolls_str = "+".join(str(r) for r in rolls)
                    mod_str = (f"+{modifier}" if modifier > 0 else str(modifier)) if modifier != 0 else ""
                    crit_s = "（大成功）" if res.get("critical_success") else ""
                    crit_f = "（大失败）" if res.get("critical_failure") else ""
                    res_lines.append(
                        f"- 投骰子（{purpose}，{formula}）：{rolls_str}{mod_str} = {total}{crit_s}{crit_f}"
                    )
                elif kind == "skill":
                    error = res.get("error")
                    if error:
                        res_lines.append(f"- 技能检定：⚠️ {error}")
                        continue
                    skill = res.get("skill", "?")
                    attr = res.get("attribute", "?")
                    d20 = res.get("d20", "?")
                    modifier = res.get("modifier", 0)
                    total = res.get("total", "?")
                    dc = res.get("dc", "?")
                    succeeded = res.get("succeeded", False)
                    crit = res.get("crit", False)
                    outcome = "大成功" if (crit and succeeded) else ("大失败" if (crit and not succeeded) else ("成功" if succeeded else "失败"))
                    mod_str = (f"+{modifier}" if modifier > 0 else str(modifier)) if modifier != 0 else ""
                    res_lines.append(
                        f"- {skill}检定（{attr}）：d20={d20}{mod_str}={total} vs DC{dc} → {outcome}"
                    )
                elif kind == "item":
                    missing = res.get("missing", False)
                    item_name_res = res.get("item_name") or inp.get("item_name", "?")
                    if missing:
                        warning = res.get("warning", f"背包没有「{item_name_res}」")
                        res_lines.append(f"- 想用「{item_name_res}」：{warning}")
                    else:
                        effects = res.get("applied_effects", [])
                        removed = res.get("removed_from_inventory", False)
                        effect_strs: list[str] = []
                        for eff in effects:
                            eff_type = eff.get("type", "")
                            amount = eff.get("amount", 0)
                            if eff_type == "heal_hp":
                                effect_strs.append(f"HP +{amount}")
                            elif eff_type == "heal_sanity":
                                effect_strs.append(f"理智 +{amount}")
                            elif eff_type == "heal_stamina":
                                effect_strs.append(f"体力 +{amount}")
                            elif eff_type == "damage":
                                effect_strs.append(f"HP -{amount}")
                            else:
                                effect_strs.append(f"{eff_type}({amount})")
                        eff_summary = "、".join(effect_strs) if effect_strs else "无即时效果"
                        removed_note = "（已消耗）" if removed else ""
                        res_lines.append(
                            f"- 使用物品（{item_name_res}）{removed_note}：{eff_summary}"
                        )
                elif kind == "attack":
                    d20 = res.get("d20", "?")
                    atk_mod = res.get("attack_mod", 0)
                    atk_total = res.get("attack_total", "?")
                    ac = res.get("ac", "?")
                    hit = res.get("hit", False)
                    dmg_total = res.get("damage_total", 0)
                    hp_before = res.get("target_hp_before", "?")
                    hp_after = res.get("target_hp_after", "?")
                    defeated = res.get("target_defeated", False)
                    atk_kind = inp.get("attacker_kind", "?")
                    tgt_kind = inp.get("target_kind", "?")
                    atk_id = res.get("attacker_id", inp.get("attacker_id", "?"))
                    tgt_id = res.get("target_id", inp.get("target_id", "?"))
                    weapon_name = inp.get("weapon", "徒手")
                    crit_s = "（大成功）" if res.get("critical_success") else ""
                    crit_f = "（大失败）" if res.get("critical_failure") else ""
                    atk_mod_str = (f"+{atk_mod}" if atk_mod >= 0 else str(atk_mod)) if atk_mod != 0 else ""
                    attacker_label = f"{atk_kind.upper()}{atk_id}"
                    target_label = f"{tgt_kind.upper()}{tgt_id}"
                    if hit:
                        dmg_formula = res.get("damage_formula") or "?"
                        dmg_rolls = res.get("damage_rolls") or []
                        dmg_mod = res.get("damage_mod", 0)
                        dmg_rolls_str = "+".join(str(r) for r in dmg_rolls)
                        dmg_mod_str = (f"+{dmg_mod}" if dmg_mod > 0 else str(dmg_mod)) if dmg_mod and dmg_mod != 0 else ""
                        defeated_note = " 已被击败" if defeated else f"（HP {hp_before}→{hp_after}）"
                        res_lines.append(
                            f"- 攻击 {attacker_label}[{weapon_name}]→{target_label}："
                            f"d20={d20}{atk_mod_str}={atk_total} vs AC{ac}{crit_s} → 命中；"
                            f"伤害 {dmg_rolls_str}{dmg_mod_str}={dmg_total}{defeated_note}"
                        )
                    else:
                        res_lines.append(
                            f"- 攻击 {attacker_label}[{weapon_name}]→{target_label}："
                            f"d20={d20}{atk_mod_str}={atk_total} vs AC{ac}{crit_f} → 未命中"
                        )
                elif kind == "initiative":
                    order = res.get("order") or []
                    order_strs = [
                        f"{entry.get('name', '?')}({entry.get('initiative_total', '?')})"
                        for entry in order
                    ]
                    res_lines.append(f"- 先攻顺序：" + " → ".join(order_strs))
                else:
                    res_lines.append(f"- [{kind}] {res}")

            if len(res_lines) > 1:  # Has entries beyond the header
                parts.append("\n".join(res_lines))

    # ── 本回合要点（动态 GM 指令）────────────────────────────────────────────
    # 这是 key_facts 的最后一块，放在最靠近 LLM 生成的位置（位置越靠后，权重越高）
    # 内容由 Python 根据当前游戏状态动态计算，而不是让 LLM 自己判断
    # 主要目的：解决常见的 GM 行为问题（场景停滞、NPC 消失、叙事单调）
    directive_items: list[str] = []

    # 场景停滞检测：如果没有 scene_turn_count 触发（场景压力块已经在处理），
    # 用"距上次访问的回合数"来检测更细粒度的场景停滞
    # 注：stc_active=True 时跳过，避免与场景压力块的指令重复
    if current_loc is not None:
        turns_in_loc = current_turn - (current_loc.last_visited_turn or 0)
        stc_active = sess is not None and (sess.scene_turn_count or 0) >= SCENE_SOFT_PRESSURE_TURNS
        if turns_in_loc >= 3 and not stc_active:
            directive_items.append(
                f"场景节奏：PC 已在「{current_loc.name}」停留 {turns_in_loc} 回合，"
                "本回合必须加入打断元素（新NPC到来/意外发现/环境变化）或引导 PC 转移场景"
            )

    # NPC 缺席检测：Pinned NPC 消失 5 回合以上时，提醒 GM 把它带回场景
    # 避免 GM 遗忘了重要 NPC，导致 PC 的关键关系线索断掉
    for n in pinned_npcs:
        if current_turn > 0 and (current_turn - (n.last_seen_turn or 0)) >= 5:
            turns_absent = current_turn - (n.last_seen_turn or 0)
            directive_items.append(
                f"NPC 回场：{n.name} 已 {turns_absent} 回合未出现"
                f"（上次第 {n.last_seen_turn} 回合），本回合安排其主动联系或被提及"
            )

    # 叙事多样性轮转：防止 GM 每回合使用同样的叙事模式（如永远是"NPC 说话+PC 回应"）
    # 用 current_turn % 4 作为索引，每 4 回合循环一次，每种要求出现 25% 的时间
    # 这比随机选择更可预测（玩家和 GM 都能感知到叙事风格在变化）
    _VARIETY = [
        "叙事质感：本回合融入一个具体感官细节（声音/气味/触感/温度），自然嵌入，不要单独列出",
        "叙事质感：安排一件出乎 PC 预料的小事或 NPC 意外反应，打破本回合的既定节奏",
        "叙事质感：在本回合末尾埋下一个未解答的悬念或细节，让玩家带着好奇进入下一回合",
        "叙事质感：聚焦情绪落差——同一场景内从平静到紧张（或反向）的节奏转变",
    ]
    # % 是取模运算符：current_turn % 4 的结果是 0/1/2/3 循环
    directive_items.append(_VARIETY[current_turn % len(_VARIETY)])

    parts.append("## 🎬 本回合要点\n" + "\n".join(f"- {d}" for d in directive_items))

    # 把所有 parts 用换行符拼接成最终的 key_facts 字符串，返回给调用方
    return "\n".join(parts)
