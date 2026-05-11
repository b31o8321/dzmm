# ============================================================
# 玩家 Agent（player_agent.py）
# ============================================================
# 【玩家 Agent 是什么？】
#   TRPG 跑团需要玩家持续输入行动（"我走向门口"、"我问 NPC 他的身份"）。
#   在自动化评测里，没有真实玩家坐在屏幕前——所以我们用一个 LLM 来
#   "扮演"玩家角色，根据角色背景和最近的剧情自动生成合理的行动。
#
# 【设计哲学】
#   玩家 Agent 不追求"聪明"，而是追求"真实感"：
#   - 行动要符合角色的性格和背景（由 character_md 约束）
#   - 行动要回应最近的 GM 叙事（由 recent_history 提供上下文）
#   - 行动不要太长（max_tokens=100，大约 60-80 个汉字）
#   - 如果 LLM 调用失败，有预设的保底回退行动（避免评测崩溃）
#
# 【消息历史转换逻辑】
#   数据库里存的消息是"用户消息 + 助手消息"交替的格式：
#     user: "我走向门口"    ← 玩家之前的行动（已存入数据库）
#     assistant: "你推开..."  ← GM 的回应
#     user: "我拿起蜡烛"   ← 再次行动
#     assistant: "烛火..."  ← 再次回应
#   Player Agent 的提示词需要的格式是"(玩家输入, GM回应)"的配对列表。
#   generate_player_action() 负责把数据库消息列表转换成这种配对格式。
# ============================================================
import logging
from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.player_template import build_player_messages

log = logging.getLogger(__name__)

# 玩家 Agent 的生成参数
# temperature=0.8：有一定随机性，让每次的行动不完全相同（避免重复）
# max_tokens=100：行动要简短，不需要长篇大论（玩家输入通常是一两句话）
_PLAYER_PARAMS = GenerationParams(temperature=0.8, max_tokens=100)


async def generate_player_action(
    messages: list,        # 数据库里的 Message ORM 对象列表（最近 N 条）
    character_md: str,     # 角色背景描述（Markdown 格式，约束角色行为风格）
    character_name: str,   # 角色名称（如"楚晓"，用于提示词里的称呼）
    client: ModelClient,   # 要使用的 LLM 客户端（和 GM 共用同一个）
) -> str:
    # ── 第一步：把数据库消息转换成 (玩家行动, GM回应) 配对列表 ──────────
    # pairs 是"对话对"的列表，格式：[(玩家行动1, GM回应1), (玩家行动2, GM回应2), ...]
    # 玩家 Agent 的提示词模板需要这种配对格式（定义在 player_template.py 里）
    pairs: list[tuple[str, str]] = []
    user_msg: str | None = None  # 暂存当前已看到的 user 消息，等待匹配对应的 assistant 消息

    for msg in messages:
        if msg.role == "user":
            # 看到 user 消息，先暂存（还没看到对应的 GM 回应）
            user_msg = msg.content
        elif msg.role == "assistant" and user_msg is not None:
            # 看到 assistant 消息，且前面有待配对的 user 消息：形成一对
            pairs.append((user_msg, msg.content))
            user_msg = None  # 配对完成，清空暂存

    # ── 第二步：构建玩家 Agent 的提示词消息列表 ──────────────────────
    # build_player_messages() 定义在 player_template.py，返回 [Message(role=...), ...]
    # 该函数会生成系统提示词（角色背景 + 扮演说明）和对话历史
    prompt_msgs = build_player_messages(
        character_name=character_name,
        character_md=character_md,
        recent_history=pairs,
    )

    # ── 第三步：调用 LLM 生成玩家行动 ────────────────────────────────
    try:
        # client.complete() 是阻塞式调用（等 LLM 输出完才返回），返回 (文本, token用量)
        action, _ = await client.complete(prompt_msgs, _PLAYER_PARAMS)
        action = action.strip()  # 去掉首尾空白字符（LLM 经常在开头加换行）

        if not action:
            # LLM 返回了空字符串（极少见但可能发生）：用保底行动
            # 这个行动很通用，任何场景都适用
            return "我四处张望，等待下一步的线索。"
        return action
    except Exception as exc:
        # 任何异常（网络错误/超时/API 限流/模型返回异常）都用保底行动
        # 这样单次 LLM 调用失败不会导致整个评测循环崩溃
        # log.warning 而不是 log.error：这是可预期的偶发失败，不需要报警
        log.warning("player_agent failed: %s", exc)
        return "我思考了一下，决定继续观察周围的环境。"  # 保底行动 B（语义略不同，更通用）
