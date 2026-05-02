"""POST /sessions/{id}/suggest_actions — generate 3 contextual action hints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import build_client, get_session_dep
from dzmm.db.models import ModelConfig, Session as GameSession
from dzmm.models.client import GenerationParams

router = APIRouter(prefix="/sessions", tags=["sessions"])


class SuggestRequest(BaseModel):
    narrative: str
    goals: list[str] = []


@router.post("/{session_id}/suggest_actions")
async def suggest_actions(
    session_id: int,
    body: SuggestRequest,
    s: AsyncSession = Depends(get_session_dep),
):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    cfg = await s.get(ModelConfig, sess.gm_model_config_id)
    if cfg is None:
        raise HTTPException(404, "model config not found")

    client = build_client(cfg)
    narrative_snippet = body.narrative[:400] if body.narrative else ""
    goals_text = "、".join(body.goals[:3]) if body.goals else "无"

    messages = [
        {
            "role": "system",
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
            "content": f"当前场景：{narrative_snippet}\n当前目标：{goals_text}",
        },
    ]

    chunks: list[str] = []
    try:
        async for ch in client.stream(
            messages, GenerationParams(max_tokens=120, temperature=0.8)
        ):
            if ch.delta:
                chunks.append(ch.delta)
    except Exception:
        return {"suggestions": []}

    raw = "".join(chunks).strip()
    suggestions = [line.strip() for line in raw.splitlines() if line.strip()][:3]
    return {"suggestions": suggestions}
