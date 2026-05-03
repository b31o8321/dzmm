# ============================================================
# Phase B — LangGraph 多 Agent GM 管线
# ============================================================
# 【架构说明】
#   把 GM 拆成三个阶段：
#     1. 规则预处理（Pre-pass）— LangGraph StateGraph
#        rules_node 分析行动类型和技能检定需求
#        → 条件边：有检定 → dice_enrich_node；无检定 → END
#     2. 主叙事生成（Narrative）— 现有流式生成，不变
#     3. NPC 后处理（Post-pass）— 独立异步函数
#        检查在场 NPC 是否有遗漏反应
#
# 【LangGraph 核心概念】
#   StateGraph:  有向图，节点是状态处理函数，边是流程控制
#   TypedDict:   图状态的类型定义（类似 Java 的 DTO/Record）
#   add_node:    注册一个处理步骤
#   add_conditional_edges: 根据状态内容决定下一步走哪个节点
#   compile():   把图编译成可执行对象
#   ainvoke():   异步执行整个图，返回最终状态
# ============================================================

import logging
from typing import TypedDict

from langgraph.graph import END, StateGraph

from dzmm.models.client import GenerationParams, ModelClient
from dzmm.parsing.events import ParseEvent, TagComplete
from dzmm.parsing.stream_parser import StreamingTagParser
from dzmm.prompts.npc_react_template import build_npc_react_messages
from dzmm.prompts.rules_template import build_rules_messages

log = logging.getLogger(__name__)

_RULES_PARAMS = GenerationParams(temperature=0.3, max_tokens=120)
_NPC_PARAMS = GenerationParams(temperature=0.5, max_tokens=300)


# ── LangGraph 状态定义 ────────────────────────────────────
class PrePassState(TypedDict):
    key_facts: str
    user_action: str
    rules_enrichment: str


# ── 节点函数 ──────────────────────────────────────────────
def make_rules_node(client: ModelClient):
    """工厂函数：返回一个绑定了 client 的 rules_node（闭包注入依赖）。"""
    async def rules_node(state: PrePassState) -> PrePassState:
        msgs = build_rules_messages(state["key_facts"], state["user_action"])
        output, _ = await client.complete(msgs, _RULES_PARAMS)
        return {**state, "rules_enrichment": output.strip()}
    return rules_node


async def dice_enrich_node(state: PrePassState) -> PrePassState:
    """条件节点：当 rules_node 检测到技能检定需求时，高亮骰子上下文。"""
    enrichment = state["rules_enrichment"]
    highlighted = "🎲 **骰子检定预告（仅 GM 可见）**\n" + enrichment
    return {**state, "rules_enrichment": highlighted}


def _route_after_rules(state: PrePassState) -> str:
    """条件边路由：根据规则分析结果决定下一步。"""
    enrichment = state.get("rules_enrichment", "")
    if "检定" in enrichment and "DC" in enrichment:
        return "dice_enrich"
    return END


# ── 图构建 ───────────────────────────────────────────────
def make_pre_pass_graph(client: ModelClient):
    """构建并编译 pre-pass StateGraph。"""
    builder = StateGraph(PrePassState)
    builder.add_node("rules", make_rules_node(client))
    builder.add_node("dice_enrich", dice_enrich_node)
    builder.set_entry_point("rules")
    builder.add_conditional_edges(
        "rules",
        _route_after_rules,
        {"dice_enrich": "dice_enrich", END: END},
    )
    builder.add_edge("dice_enrich", END)
    return builder.compile()


# ── 公共 API ─────────────────────────────────────────────
async def run_pre_pass(
    key_facts: str,
    user_action: str,
    client: ModelClient,
) -> str:
    """运行预处理图，返回注入了规则分析的增强版 key_facts。失败时回退到原始值。"""
    try:
        graph = make_pre_pass_graph(client)
        initial: PrePassState = {
            "key_facts": key_facts,
            "user_action": user_action,
            "rules_enrichment": "",
        }
        result = await graph.ainvoke(initial)
        enrichment = result.get("rules_enrichment", "")
        if enrichment:
            return key_facts + "\n\n## 🎮 规则分析（仅 GM 可见）\n" + enrichment
    except Exception as exc:
        log.warning("gm_graph pre_pass failed, using original key_facts: %s", exc)
    return key_facts


async def run_npc_post_pass(
    narrative: str,
    present_npcs: list[str],
    user_action: str,
    client: ModelClient,
) -> list[ParseEvent]:
    """NPC 后处理：检查在场 NPC 是否有遗漏反应，返回额外 TagComplete 事件。"""
    if not present_npcs:
        return []
    try:
        msgs = build_npc_react_messages(narrative, present_npcs, user_action)
        output, _ = await client.complete(msgs, _NPC_PARAMS)
        if not output.strip() or 'name="none"' in output:
            return []
        parser = StreamingTagParser()
        events: list[ParseEvent] = []
        for ev in parser.feed(output):
            if isinstance(ev, TagComplete) and ev.name == "npc_update":
                events.append(ev)
        events.extend(ev for ev in parser.finish()
                      if isinstance(ev, TagComplete) and ev.name == "npc_update")
        return events
    except Exception as exc:
        log.warning("gm_graph npc_post_pass failed: %s", exc)
        return []
