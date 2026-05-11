# ============================================================
# suggest.py — 玩家行动建议 API
# ============================================================
#
# 【这个接口是做什么的？】
#   在跑团游戏中，玩家有时会卡壳——不知道下一步该做什么。
#   这个接口让 LLM 根据当前场景和玩家目标，自动生成 3 条行动建议，
#   类似于手机游戏里的"快捷指令"或"行动提示"。
#
# 【为什么是 3 条？为什么要覆盖不同风险档？】
#   3 条是经验数字：够用但不多，不会让玩家选择困难。
#   覆盖不同风险是因为不同玩家的风格不同：
#   - 喜欢冒险的玩家会选高风险高回报的行动
#   - 谨慎的玩家会选低风险稳进的行动
#   - 专注主线的玩家会选推进剧情的行动
#   这样三条建议能满足不同风格的玩家需求。
#
# 【为什么用流式（stream）而不是一次性返回？】
#   这里实际上用的是 stream 方式调用 LLM，但最后把所有片段拼接起来一次性返回。
#   因为行动建议本身很短（每条不超过 16 字），全部生成完总共也就几秒，
#   所以没有必要做 SSE 流式推送，一次性返回更简单。
#   用 stream 调用 LLM 是因为底层客户端的统一接口是流式的。

"""POST /sessions/{id}/suggest_actions — generate 3 contextual action hints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

# build_client — 构建 LLM 客户端（注意这里从 _common 模块导入，是路由层共用的版本）
from dzmm.api.routes_sessions._common import build_client, get_session_dep
from dzmm.db.models import ModelConfig, Session as GameSession

# GenerationParams — 封装 LLM 生成参数（max_tokens、temperature 等）
from dzmm.models.client import GenerationParams

router = APIRouter(prefix="/sessions", tags=["sessions"])


# 请求体：前端传来的上下文信息
class SuggestRequest(BaseModel):
    narrative: str          # 当前场景的叙述文本（GM 最近说的话）
    goals: list[str] = []   # 玩家当前的目标列表（可以为空）


# POST /sessions/{session_id}/suggest_actions
# 根据当前场景和目标，生成 3 条行动建议
@router.post("/{session_id}/suggest_actions")
async def suggest_actions(
    session_id: int,
    body: SuggestRequest,
    s: AsyncSession = Depends(get_session_dep),
):
    # 验证存档存在，并获取 GM 模型配置 id
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    cfg = await s.get(ModelConfig, sess.gm_model_config_id)
    if cfg is None:
        raise HTTPException(404, "model config not found")

    # 构建 LLM 客户端（使用 GM 同款模型）
    client = build_client(cfg)

    # 截取场景文本的前 400 字，防止 prompt 太长（行动建议不需要完整的上下文）
    narrative_snippet = body.narrative[:400] if body.narrative else ""
    # 把目标列表拼成"目标1、目标2、目标3"格式；如果没有目标则显示"无"
    goals_text = "、".join(body.goals[:3]) if body.goals else "无"

    # 构建 LLM 对话消息列表（OpenAI 格式：system prompt + user message）
    messages = [
        {
            "role": "system",
            # system prompt：告诉 LLM 它的角色是"行动建议助手"，并给出格式规则
            "content": (
                "你是 TRPG 助手，根据当前场景和玩家目标，给出 3 个行动建议。\n"
                "规则：\n"
                "- 每条不超过 16 个汉字（含括号内的后果提示）\n"
                "- 三个建议必须覆盖不同风险档：至少一个高风险高回报、至少一个低风险稳进\n"
                "- 至少一个直接推进当前目标或主线剧情\n"
                "- 可选：在行动后用括号标注关键后果，例如「强攻（可能暴露）」\n"
                "- 只输出 3 行，每行一个，不加序号不加解释"
            ),
        },
        {
            "role": "user",
            # user message：提供当前场景和目标作为上下文
            "content": f"当前场景：{narrative_snippet}\n当前目标：{goals_text}",
        },
    ]

    # 收集 LLM 流式输出的所有文本片段
    chunks: list[str] = []
    try:
        # client.stream() 是异步生成器，每次 yield 一个 chunk 对象
        async for ch in client.stream(
            messages,
            # max_tokens=120 限制输出长度（3条×每条约 16 字 = ~48 字，留足余量）
            # temperature=0.8 增加一些随机性，让建议不会每次都一模一样
            GenerationParams(max_tokens=120, temperature=0.8)
        ):
            if ch.delta:
                chunks.append(ch.delta)  # ch.delta 是本次 chunk 新增的文本
    except Exception:
        # 如果 LLM 调用失败，返回空建议列表（不报错，让玩家继续游戏）
        return {"suggestions": []}

    # 把所有片段拼接成完整文本，按行分割，每行是一条建议
    raw = "".join(chunks).strip()
    # splitlines() 按换行符分割；[:3] 最多取 3 条防止 LLM 输出超过 3 行
    suggestions = [line.strip() for line in raw.splitlines() if line.strip()][:3]
    return {"suggestions": suggestions}
