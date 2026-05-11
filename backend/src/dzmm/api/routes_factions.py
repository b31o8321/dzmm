"""Factions API: list."""
# ============================================================
# routes_factions.py — 派系（Faction）的 REST API 路由
#
# 「派系」= 跑团世界中的政治/社会团体，例如：
#   帝国军 / 地下抵抗组织 / 商人公会 等
#
# 派系有以下关键属性：
#   - 意识形态（ideology）
#   - 领袖 NPC（leader_npc_id）
#   - 玩家声誉（pc_reputation：正=友好，负=敌对）
#   - 与其他派系的关系（hostile_to / allied_to）
#
# 当前版本只提供只读的「列表」接口；派系的创建/修改
# 由 GM AI 在跑团过程中自动完成。
# ============================================================

import json  # 用于解析存储为 JSON 字符串的列表字段

# FastAPI 核心组件
from fastapi import APIRouter, Depends
from sqlalchemy import select                       # SQL 查询构建器
from sqlalchemy.ext.asyncio import AsyncSession     # 异步数据库会话

# 注意：这里直接从 routes_sessions._common 导入依赖，
# 因为派系路由挂载在 /sessions 前缀下（见下方 router 定义）
from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import Faction  # 数据库派系 ORM 模型

# 创建路由组：注意前缀是 /sessions（不是 /factions）
# 因为派系属于某个跑团存档，URL 结构为 /sessions/{session_id}/factions
router = APIRouter(prefix="/sessions", tags=["factions"])


# _faction_dict：把数据库 ORM 对象（Faction）转成 Python 字典
# （这里没有定义 Pydantic Out 类，直接用 dict 返回，更灵活）
def _faction_dict(f: Faction) -> dict:
    return {
        "id": f.id,
        "name": f.name,
        "ideology": f.ideology,         # 派系的核心信念/意识形态
        "description": f.description,   # 派系描述
        "leader_npc_id": f.leader_npc_id,  # 领袖 NPC 的 ID（可为空）
        "pc_reputation": f.pc_reputation,  # 玩家对该派系的声誉值
        # 以下两个字段在数据库中存为 JSON 字符串，读出时解析成 Python 列表
        "hostile_to": json.loads(f.hostile_to_json or "[]"),   # 敌对派系 ID 列表
        "allied_to": json.loads(f.allied_to_json or "[]"),     # 同盟派系 ID 列表
    }


# ──────────────────────────────────────────────
# GET /sessions/{session_id}/factions — 获取某存档下的所有派系
# ──────────────────────────────────────────────

@router.get("/{session_id}/factions")
async def list_factions(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    # 查询属于该跑团存档的所有派系，按 id 升序排列
    rows = (await s.execute(
        select(Faction).where(Faction.session_id == session_id).order_by(Faction.id)
    )).scalars().all()
    # 把所有 ORM 对象转成字典列表返回
    return [_faction_dict(f) for f in rows]
