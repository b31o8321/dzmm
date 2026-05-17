# ============================================================
# wizard_framework.py — 开放世界框架向导服务
# ============================================================
# 【什么是 WorldFramework（世界框架）？】
#   WorldFramework 是游戏地图的"骨架"，包含：
#   - WorldLocation（地点）：城市、村庄、地下城等，及相互之间的连接
#   - WorldFaction（派系）：玩家可以加入或对抗的阵营
#   - WorldNPCTemplate（NPC 模板）：可在世界里重复出现的角色原型
#   - WorldEvent（世界事件）：有触发条件的重要事件
#   - Campaign（战役）：由多个阶段组成的主线任务结构
#
# 【与 Screenplay 的区别】
#   Screenplay（剧本）是线性的故事大纲，适合短篇、聚焦的叙事。
#   WorldFramework 是开放世界的地图/规则骨架，适合沙盒式探索游戏。
#   玩家可以在 Framework 的世界里自由生成 Screenplay 剧本。
#
# 【生成流程（逐层生成）】
#   1. generate_locations: 生成地点列表（连接关系只有名字）
#   2. generate_factions:  生成派系（知道地点名字）
#   3. generate_npc_templates: 生成 NPC 模板（知道地点+派系）
#   4. generate_events:    生成世界事件（知道地点+派系+NPC）
#   5. generate_campaign:  生成战役阶段（知道事件列表）
#   6. finalize_framework: 原子性写入数据库（名字引用解析为 ID）
#
# 【名字 → ID 的解析（finalize_framework 的核心工作）】
#   LLM 生成时用名字引用其他实体（如 NPC 的 home_location_name="黑石城"），
#   但数据库需要 FK（外键）ID。finalize_framework 负责把名字解析成 ID。
# ============================================================
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.wizard_locations import build_locations_messages
from dzmm.prompts.wizard_factions_fw import build_factions_messages
from dzmm.prompts.wizard_npc_templates import build_npc_templates_messages
from dzmm.prompts.wizard_events_fw import build_events_messages
from dzmm.prompts.wizard_campaign_fw import build_campaign_messages
from dzmm.db.models import (
    WorldFramework,     # 世界框架主表
    WorldLocation,      # 地点
    WorldFaction,       # 派系
    WorldNPCTemplate,   # NPC 模板
    WorldEvent,         # 世界事件
    Campaign,           # 战役
)

log = logging.getLogger(__name__)

# 所有生成调用使用统一的参数：温度 0.7（有一定创意），最多 4096 token
_PARAMS = GenerationParams(temperature=0.7, max_tokens=4096)

# 正则：剥除 markdown 围栏（```json ... ```）
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
# 正则：修复 JSON 尾部多余逗号（如 {..., }）
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _resolve_predicate(
    pred: dict,
    *,
    loc_map: dict[str, int],
    npc_map: dict[str, int],
    faction_map: dict[str, int],
) -> dict:
    """Recursively resolve name→id in a v0.15 predicate dict.

    The LLM emits human-readable names (location_name, npc_template_name,
    faction_name). We translate them to integer IDs so the engine can do
    fast equality comparisons at runtime.

    Unknown names are resolved to 0 (inert — the evaluator will miss and
    the condition stays False, which is safe for unrecognised references).

    Malformed / non-dict input is replaced with the inert always-False
    predicate {"type": "all", "children": []}.
    """
    if not isinstance(pred, dict):
        log.warning("_resolve_predicate: expected dict, got %r — replacing with inert", type(pred))
        return {"type": "all", "children": []}

    pred_type = pred.get("type", "")

    # Recurse into combined predicates (all / any)
    if pred_type in ("all", "any"):
        resolved_children = [
            _resolve_predicate(child, loc_map=loc_map, npc_map=npc_map, faction_map=faction_map)
            for child in pred.get("children", [])
        ]
        return {"type": pred_type, "children": resolved_children}

    result = dict(pred)

    # location_reached: location_name → location_id
    if pred_type == "location_reached" and "location_name" in result:
        name = result.pop("location_name")
        result["location_id"] = loc_map.get(name, 0)

    # npc_state: npc_template_name → npc_template_id
    elif pred_type == "npc_state" and "npc_template_name" in result:
        name = result.pop("npc_template_name")
        result["npc_template_id"] = npc_map.get(name, 0)

    # faction_tension: faction_name → faction_id
    elif pred_type == "faction_tension" and "faction_name" in result:
        name = result.pop("faction_name")
        result["faction_id"] = faction_map.get(name, 0)

    # stat_threshold and item_owned have no name references — pass through as-is
    return result


def _extract_json(text: str) -> str:
    # 从 LLM 返回的文本中提取最外层 JSON 对象（{...}）或数组（[...]）
    # 并修复尾部逗号问题（本地模型的常见问题）
    text = text.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    # 判断是数组还是对象，找到对应的最外层边界
    obj = text.find("{")
    arr = text.find("[")
    if arr != -1 and (obj == -1 or arr < obj):
        # 以数组 [...] 为主
        end = text.rfind("]")
        if end != -1:
            text = text[arr:end+1]
    elif obj != -1:
        # 以对象 {...} 为主
        end = text.rfind("}")
        if end != -1:
            text = text[obj:end+1]
    # 修复尾部逗号
    text = _TRAILING_COMMA_RE.sub(r"\1", text)
    return text


async def generate_locations(
    genre: str, world_brief_md: str, client: ModelClient
) -> list[dict]:
    # 生成世界地点列表
    # 每个地点包含：name/description_md/location_type/connections/initial_state
    # connections 里用 target_name（地点名字）引用其他地点，finalize 时解析成 ID
    msgs = build_locations_messages(genre, world_brief_md)
    raw, _ = await client.complete(msgs, _PARAMS)  # 非流式调用（一次性返回全部）
    return json.loads(_extract_json(raw))


async def generate_factions(
    genre: str, world_brief_md: str, locations: list[dict], client: ModelClient
) -> list[dict]:
    # 生成派系列表
    # 只传地点名字给 Prompt（不传完整描述），避免 Prompt 过长
    # 每个派系包含：name/description_md/rival_faction_names/ally_faction_names/tension_rules
    location_names = [l["name"] for l in locations]
    msgs = build_factions_messages(genre, world_brief_md, location_names)
    raw, _ = await client.complete(msgs, _PARAMS)
    return json.loads(_extract_json(raw))


async def generate_npc_templates(
    genre: str, world_brief_md: str, locations: list[dict],
    factions: list[dict], client: ModelClient,
) -> list[dict]:
    # 生成 NPC 模板列表
    # NPC 模板是世界里可以重复出现的角色原型，如"铁匠 老张"
    # 每个模板有 home_location_name（常驻地点名）和 faction_name（所属派系名）
    location_names = [l["name"] for l in locations]
    faction_names = [f["name"] for f in factions]
    msgs = build_npc_templates_messages(genre, world_brief_md, location_names, faction_names)
    raw, _ = await client.complete(msgs, _PARAMS)
    return json.loads(_extract_json(raw))


async def generate_events(
    genre: str, world_brief_md: str, locations: list[dict],
    factions: list[dict], npc_templates: list[dict], client: ModelClient,
) -> list[dict]:
    # 生成世界事件列表
    # 事件有触发条件（trigger_conditions），可以是：
    # - PC 到达某个地点（type="location", location_name="黑石城"）
    # - PC 遇见某个 NPC（type="npc_met", npc_name="老铁匠"）
    # - 对某派系的声望达到阈值（type="faction_rep", faction_name="..."）
    location_names = [l["name"] for l in locations]
    faction_names = [f["name"] for f in factions]
    npc_names = [n["name"] for n in npc_templates]
    msgs = build_events_messages(genre, world_brief_md, location_names, faction_names, npc_names)
    raw, _ = await client.complete(msgs, _PARAMS)
    return json.loads(_extract_json(raw))


async def generate_campaign(
    genre: str, world_brief_md: str, events: list[dict], client: ModelClient
) -> dict:
    # 生成战役（Campaign）结构
    # 战役由多个阶段（phase）组成，每个阶段关联若干关键事件
    # 只传事件的 name 和 importance，不传完整描述（节省 token）
    event_summaries = [{"name": e["name"], "importance": e.get("importance", 2)} for e in events]
    msgs = build_campaign_messages(genre, world_brief_md, event_summaries)
    raw, _ = await client.complete(msgs, _PARAMS)
    return json.loads(_extract_json(raw))


async def finalize_framework(s: AsyncSession, payload: dict) -> int:
    # 原子性地把向导生成的所有数据写入数据库，返回新建的 WorldFramework.id
    #
    # 【名字 → ID 解析的挑战】
    #   LLM 生成时用名字引用其他实体（如 NPC 的 home_location_name="黑石城"），
    #   但数据库需要 FK ID。解决方案：
    #   - 先批量 INSERT 地点、派系、NPC，获得它们的 ID
    #   - 再用"名字 → ID"映射字典解析各处的名字引用
    #   - 地点的 connections（连接关系）需要两次遍历：
    #     第一次 INSERT 地点（此时不知道其他地点的 ID）
    #     flush 获得 ID 后，第二次遍历解析 connections_json

    # ── 创建 WorldFramework 主行 ────────────────────────────────────────
    fw = WorldFramework(
        name=payload["name"],
        genre=payload.get("genre", ""),
        style=payload.get("style", ""),
        description_md=payload.get("description_md", ""),
    )
    s.add(fw)
    await s.flush()  # flush 使 fw.id 被赋值

    # ── 地点（第一遍：只创建行，连接关系暂时为空）────────────────────────
    # 地点之间相互连接，需要所有地点都有 ID 后才能解析 target_id
    loc_name_to_id: dict[str, int] = {}  # 名字 → ID 映射
    loc_rows: list[WorldLocation] = []
    for loc_data in payload.get("locations", []):
        loc = WorldLocation(
            framework_id=fw.id,
            name=loc_data["name"],
            description_md=loc_data.get("description_md", ""),
            location_type=loc_data.get("location_type", "city"),
            connections_json="[]",  # 暂时为空，第二遍填入
            initial_state=loc_data.get("initial_state", "normal"),
        )
        s.add(loc)
        loc_rows.append(loc)
    await s.flush()  # flush 后所有地点都有 ID

    # 建立名字 → ID 映射（用于解析其他实体的引用）
    for loc, loc_data in zip(loc_rows, payload.get("locations", [])):
        loc_name_to_id[loc.name] = loc.id

    # ── 地点（第二遍：填入连接关系 connections_json）──────────────────────
    # connections 格式：[{"target_id": 3, "direction": "north", "distance": 1, "travel_turns": 2}]
    for loc, loc_data in zip(loc_rows, payload.get("locations", [])):
        resolved = []
        for conn in loc_data.get("connections", []):
            # 把 target_name（地点名字）解析为 target_id（数据库 ID）
            target_id = loc_name_to_id.get(conn.get("target_name", ""))
            if target_id:
                resolved.append({
                    "target_id": target_id,
                    "direction": conn.get("direction", ""),
                    "distance": conn.get("distance", 1),
                    "travel_turns": conn.get("travel_turns", 1),
                })
        loc.connections_json = json.dumps(resolved, ensure_ascii=False)

    # ── 派系 ──────────────────────────────────────────────────────────────
    # rival/ally 派系名字存储为 JSON 数组（不解析成 ID，避免复杂的自引用）
    faction_name_to_id: dict[str, int] = {}
    for f_data in payload.get("factions", []):
        faction = WorldFaction(
            framework_id=fw.id,
            name=f_data["name"],
            description_md=f_data.get("description_md", ""),
            rival_factions_json=json.dumps(f_data.get("rival_faction_names", []), ensure_ascii=False),
            ally_factions_json=json.dumps(f_data.get("ally_faction_names", []), ensure_ascii=False),
            tension_rules_json=json.dumps(f_data.get("tension_rules", {}), ensure_ascii=False),
        )
        s.add(faction)
        await s.flush()
        faction_name_to_id[faction.name] = faction.id

    # ── NPC 模板 ──────────────────────────────────────────────────────────
    # home_location_name → home_location_id（FK 到 WorldLocation）
    # faction_name → faction_id（FK 到 WorldFaction）
    npc_name_to_id: dict[str, int] = {}
    for n_data in payload.get("npc_templates", []):
        home_id = loc_name_to_id.get(n_data.get("home_location_name", ""))
        faction_id = faction_name_to_id.get(n_data.get("faction_name", ""))
        npc = WorldNPCTemplate(
            framework_id=fw.id,
            name=n_data["name"],
            gender=n_data.get("gender", ""),
            role=n_data.get("role", ""),
            description_md=n_data.get("description_md", ""),
            motivation=n_data.get("motivation", ""),
            home_location_id=home_id,   # 可以为 None（LLM 没有声明常驻地点）
            faction_id=faction_id,      # 可以为 None（无派系 NPC）
            # 联络触发条件：好感 ≥ threshold 时 NPC 主动联络玩家
            contact_favor_threshold=n_data.get("contact_favor_threshold", 70),
            # 同一 NPC 两次主动联络之间的最少回合间隔
            contact_cooldown_turns=n_data.get("contact_cooldown_turns", 10),
            # v0.53: 1-sentence verbal tic (may be absent in older LLM outputs)
            speech_pattern=n_data.get("speech_pattern", ""),
        )
        s.add(npc)
        await s.flush()
        npc_name_to_id[npc.name] = npc.id

    # ── 世界事件 ──────────────────────────────────────────────────────────
    # trigger_conditions 里的名字引用需要解析为 ID
    event_name_to_id: dict[str, int] = {}
    for e_data in payload.get("events", []):
        # scope_ref：事件影响范围的 ID（地点 ID 或派系 ID，以字符串存储）
        scope_ref = ""
        if e_data.get("scope_type") == "location":
            scope_ref = str(loc_name_to_id.get(e_data.get("scope_location_name", ""), ""))
        elif e_data.get("scope_type") == "faction":
            scope_ref = str(faction_name_to_id.get(e_data.get("scope_faction_name", ""), ""))

        # 解析触发条件谓词（v0.15 格式）：名字引用 → ID
        raw_pred = e_data.get("trigger_conditions", {"type": "all", "children": []})

        # 向后兼容：旧格式是列表（[{type:"location",...}, ...]），新格式是单个谓词对象
        if isinstance(raw_pred, list):
            # 旧列表格式：将每个条件转换为新谓词形式，包装成 all
            converted_children = []
            for cond in raw_pred:
                c = dict(cond)
                old_type = c.get("type", "")
                if old_type == "location":
                    c["type"] = "location_reached"
                elif old_type == "npc_met":
                    c["type"] = "npc_state"
                    c.setdefault("state", "alive")
                elif old_type == "faction_rep":
                    c["type"] = "faction_tension"
                # stat_gte → stat_threshold
                elif old_type == "stat_gte":
                    c["type"] = "stat_threshold"
                    c["op"] = "gte"
                converted_children.append(c)
            raw_pred = {"type": "all", "children": converted_children} if converted_children else {"type": "all", "children": []}

        # Resolve name→id recursively using the v0.15 helper
        resolved_pred = _resolve_predicate(
            raw_pred,
            loc_map=loc_name_to_id,
            npc_map=npc_name_to_id,
            faction_map=faction_name_to_id,
        )

        event = WorldEvent(
            framework_id=fw.id,
            name=e_data["name"],
            summary_md=e_data.get("summary_md", ""),
            scope_type=e_data.get("scope_type", "global"),  # global/location/faction
            scope_ref=scope_ref,
            importance=e_data.get("importance", 2),          # 1=次要 2=重要 3=关键
            trigger_conditions_json=json.dumps(resolved_pred, ensure_ascii=False),
            is_repeatable=e_data.get("is_repeatable", False),  # 是否可重复触发
            cooldown_turns=e_data.get("cooldown_turns", 0),    # 重复触发冷却回合数
        )
        s.add(event)
        await s.flush()
        event_name_to_id[event.name] = event.id

    # ── 战役（可选）──────────────────────────────────────────────────────
    # 战役阶段的 key_event_names → key_event_ids（解析事件名字为 ID）
    campaign_data = payload.get("campaign")
    if campaign_data:
        phases = []
        for ph in campaign_data.get("phases", []):
            # 把阶段关联的事件名字列表解析为 ID 列表（找不到的名字跳过）
            key_ids = [event_name_to_id[n] for n in ph.get("key_event_names", []) if n in event_name_to_id]
            phases.append({
                "phase_id": ph["phase_id"],                # 阶段唯一标识（如 1, 2, 3）
                "name": ph["name"],
                "description": ph.get("description", ""),
                "prerequisite_phase_ids": ph.get("prerequisite_phase_ids", []),  # 前置阶段 ID
                "key_event_ids": key_ids,                  # 本阶段的关键事件 ID 列表
                "required_count": ph.get("required_count", 1),  # 需要完成几个关键事件才算过阶段
            })
        campaign = Campaign(
            framework_id=fw.id,
            name=campaign_data["name"],
            phases_json=json.dumps(phases, ensure_ascii=False),
        )
        s.add(campaign)

    await s.commit()   # 提交所有数据（framework.py 里的 generate_* 函数不提交，这里统一提交）
    return fw.id       # 返回新建的 WorldFramework ID，供调用方后续操作
