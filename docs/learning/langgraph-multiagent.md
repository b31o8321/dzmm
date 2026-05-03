# Phase B：LangGraph 多 Agent GM 实现

> **v0.5.0 开始支持**。通过 `use_graph` 会话设置开启。

---

## 1. 为什么需要 LangGraph？

### 问题：单 Agent 7B 模型的瓶颈

现有 GM 流程是**单一 LLM 调用**：

```
System Prompt = 
  + 世界观（RAG 检索）
  + 规则库
  + NPC 数据
  + 剧情剧本
  + ...
↓
一个 7B 模型要同时：
  1. 判断玩家行动是否合法（规则裁定）
  2. 决定是否骰子检定（规则引擎）
  3. 生成沉浸叙事（创意写作）
  4. 管理 NPC 反应（多角色扮演）
  5. 推进剧情（宏观节奏）
```

**7B 模型吃不消**。结果：
- 规则判定频繁出错
- 叙事被规则问题打断
- NPC 反应遗漏或重复
- 剧情推进卡顿

### 方案：用 LangGraph 拆成多个专职 Agent

```
玩家行动
    ↓
[规则预处理 Agent]
  ├─ 只看：行动类型、技能检定
  ├─ 只做：是否需要骰子？规则冲突吗？
  └─ 输出：增强版 key_facts（含规则指令）
    ↓ (骰子结果)
[骰子工具]
  └─ 更新 key_facts
    ↓
[主叙事 Agent]（现有流程）
  ├─ 输入：规则预处理后的 key_facts
  ├─ 只做：流式生成沉浸叙事 + 在场角色反应
  └─ 输出：story_text
    ↓
[NPC 后处理 Agent]
  ├─ 检查：有没有遗漏的在场 NPC？
  ├─ 只做：补充被遗漏的 NPC 反应
  └─ 输出：npc_updates
    ↓
[剧情推进 Agent]（可选）
  ├─ 检查：剧本进度该推进吗？
  └─ 输出：plot_event
```

**分工的好处**：
- 规则 Agent：专注检合法性 → 判定更准确
- 主叙事 Agent：不用操心规则 → 创意更充分
- NPC Agent：只补遗漏 → 角色更立体
- 现有解析和状态管理 **完全不改**

---

## 2. LangGraph 核心 API

### StateGraph：有状态的 Agent 工作流

```python
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated

# 第一步：定义状态对象
class GMState(TypedDict):
    """GM 工作流的状态容器"""
    player_action: str
    key_facts: dict  # 包含世界、角色、规则
    requires_dice: bool
    dice_result: dict | None
    narrative: str
    npc_updates: list[dict]
    error: str | None
```

### Node：工作流的每一步

```python
async def rules_node(state: GMState) -> dict:
    """规则预处理 Agent
    
    输入：player_action + key_facts
    输出：增强版 key_facts（含规则检定指令）
    """
    from backend.prompts.rules_template import build_rules_prompt
    
    # 构建规则判定 Prompt
    prompt = build_rules_prompt(
        action=state["player_action"],
        rules=state["key_facts"]["rules"],
        skills=state["key_facts"]["skills"]
    )
    
    # 调用规则 Agent
    response = await client.stream(prompt)
    
    # 解析规则判定结果
    requires_dice = "需要检定" in response
    
    return {
        "requires_dice": requires_dice,
        "key_facts": {
            **state["key_facts"],
            "rule_decision": response  # 注入规则指令
        }
    }

async def narrative_node(state: GMState) -> dict:
    """主叙事 Agent（现有流程）
    
    输入：规则预处理后的 key_facts
    输出：story_text
    """
    # 现有的 run_turn() 逻辑
    narrative = await generate_narrative(state["key_facts"])
    
    return {
        "narrative": narrative
    }

async def npc_react_node(state: GMState) -> dict:
    """NPC 后处理 Agent
    
    输入：叙事内容 + 在场 NPC 列表
    输出：遗漏的 NPC 反应
    """
    from backend.prompts.npc_react_template import build_npc_react_prompt
    
    prompt = build_npc_react_prompt(
        narrative=state["narrative"],
        npcs=state["key_facts"]["npcs"],
        scene=state["key_facts"]["scene"]
    )
    
    response = await client.stream(prompt)
    updates = parse_npc_updates(response)
    
    return {
        "npc_updates": updates
    }
```

### 条件边：动态路由

```python
def should_use_dice(state: GMState) -> str:
    """条件判断：规则 Agent 的输出决定下一步
    
    返回值是下一个 node 的名字
    """
    if state["requires_dice"]:
        return "dice_enrich"  # 有检定，调用骰子工具
    else:
        return "narrative"    # 无检定，直接叙事
```

### 图的定义

```python
graph = StateGraph(GMState)

# 添加 node
graph.add_node("rules", rules_node)
graph.add_node("dice_enrich", dice_enrich_node)
graph.add_node("narrative", narrative_node)
graph.add_node("npc_react", npc_react_node)

# 连接：START → rules
graph.add_edge(START, "rules")

# 条件边：rules 的输出决定去 dice_enrich 还是 narrative
graph.add_conditional_edges(
    "rules",
    should_use_dice,
    {
        "dice_enrich": "dice_enrich",
        "narrative": "narrative"
    }
)

# dice_enrich → narrative
graph.add_edge("dice_enrich", "narrative")

# narrative → npc_react
graph.add_edge("narrative", "npc_react")

# npc_react → END
graph.add_edge("npc_react", END)

gm_graph = graph.compile()
```

### 执行图

```python
async def run_gm_turn_with_graph(state_dict: dict) -> dict:
    """使用 LangGraph 执行一个回合"""
    
    # ainvoke：异步调用，返回最终状态
    result = await gm_graph.ainvoke(
        input=state_dict,
        config={"recursion_limit": 25}
    )
    
    return result
```

---

## 3. 闭包注入：依赖管理模式

### 问题：Node 函数如何访问 DB、LLM client 等外部资源？

```python
# ❌ 不能这样（全局状态不好维护）
client = None  # 全局变量

async def rules_node(state: GMState):
    response = await client.stream(...)  # 危险

# ✓ 要这样（闭包注入）
```

### 解决：工厂函数 + 闭包

```python
def create_rules_node(client: ModelClient, db: AsyncSession):
    """工厂函数：创建 rules_node，注入依赖"""
    
    async def rules_node(state: GMState) -> dict:
        # client 和 db 通过闭包访问
        response = await client.stream(prompt)
        
        # 如果需要 DB 查询
        rules = await db.execute(
            select(Rule).where(Rule.game_id == state["game_id"])
        )
        
        return {...}
    
    return rules_node

# 使用
client = OllamaClient(...)
async with AsyncSession(engine) as db:
    rules_node = create_rules_node(client, db)
    graph.add_node("rules", rules_node)
```

### 在项目中的应用

```python
# backend/service/gm_graph.py

class GMGraphBuilder:
    """构建 GM LangGraph 的工厂类"""
    
    def __init__(self, client: ModelClient, db_pool, game_id: str):
        self.client = client
        self.db_pool = db_pool
        self.game_id = game_id
    
    def build(self) -> Runnable:
        """构建完整的 GM 图"""
        
        # 所有 node 都通过工厂创建，依赖注入
        rules_node = self._create_rules_node()
        narrative_node = self._create_narrative_node()
        npc_react_node = self._create_npc_react_node()
        
        graph = StateGraph(GMState)
        graph.add_node("rules", rules_node)
        graph.add_node("narrative", narrative_node)
        graph.add_node("npc_react", npc_react_node)
        # ... 连接 edges
        
        return graph.compile()
    
    def _create_rules_node(self):
        """工厂方法：创建 rules node（注入 client、db、game_id）"""
        async def rules_node(state: GMState) -> dict:
            async with self.db_pool() as session:
                rules = await fetch_rules(session, self.game_id)
            
            prompt = build_rules_prompt(
                action=state["player_action"],
                rules=rules
            )
            response = await self.client.stream(prompt)
            return {"requires_dice": "需要检定" in response}
        
        return rules_node
```

---

## 4. 条件边：智能路由

### 什么是条件边？

在工作流中，**下一步往往取决于当前 node 的输出**。

```
规则 Agent 说"需要检定"？
  → 是 → 调骰子工具
  → 否 → 直接叙事
```

在 LangGraph 中：

```python
# 条件函数：根据 state 返回下一个 node 的名字
def should_use_dice(state: GMState) -> str:
    return "dice_enrich" if state["requires_dice"] else "narrative"

# 添加条件边
graph.add_conditional_edges(
    source="rules",                      # 从哪个 node 出发
    path=should_use_dice,               # 条件函数
    path_map={                          # 返回值 → node 名字的映射
        "dice_enrich": "dice_enrich",
        "narrative": "narrative"
    }
)
```

### 示例：多分支条件

```python
def route_by_action_type(state: GMState) -> str:
    """根据行动类型路由到不同的处理 node"""
    action_type = state["key_facts"].get("action_type")
    
    if action_type == "combat":
        return "combat_rules"      # 战斗规则检查
    elif action_type == "social":
        return "social_rules"      # 社交检查
    elif action_type == "exploration":
        return "exploration_rules" # 探索检查
    else:
        return "narrative"         # 无检定，直接叙事

# 添加
graph.add_conditional_edges(
    "rules",
    route_by_action_type,
    {
        "combat_rules": "combat_rules",
        "social_rules": "social_rules",
        "exploration_rules": "exploration_rules",
        "narrative": "narrative"
    }
)
```

---

## 5. 与现有架构的集成

### 向后兼容：use_graph 设置

```python
# backend/api/routes_sessions/turn.py

async def take_turn(session_id: str, action: str):
    session = await fetch_session(session_id)
    use_graph = session.settings_json.get("use_graph", False)
    
    if use_graph:
        # 新路径：LangGraph
        result = await run_turn_with_graph(session, action)
    else:
        # 旧路径：现有单 Agent 流程
        result = await run_turn(session, action)
    
    return result
```

### 如何启用？

在前端会话设置中：

```json
{
  "use_graph": true,
  "director_pass": false
}
```

或通过 API：

```bash
PATCH /sessions/{id}
{
  "settings_json": {
    "use_graph": true
  }
}
```

### 流程对比

**旧流程（use_graph: false）**
```
玩家行动
  ↓
组装 GM Prompt（所有规则、NPC、剧情一起）
  ↓
调 LLM（单次）
  ↓
流式解析 XML 标签
  ↓
apply_tags() 更新 DB
```

**新流程（use_graph: true）**
```
玩家行动
  ↓
LangGraph 规则预处理 Agent
  ├─ 检查规则、确定骰子
  ├─ 调骰子工具
  └─ 返回 key_facts（增强版）
  ↓
主叙事 Agent（现有逻辑，输入改为预处理后的 key_facts）
  ├─ 流式解析 XML 标签
  └─ 返回 narrative
  ↓
NPC 后处理 Agent
  ├─ 检查遗漏的 NPC 反应
  └─ 补充 npc_updates
  ↓
apply_tags() 更新 DB（不变）
```

### 代码集成点

```python
# backend/service/game.py

async def run_turn(game: Game, action: str):
    """执行一个回合"""
    
    use_graph = game.session.settings_json.get("use_graph", False)
    
    if use_graph:
        # 新：使用 LangGraph
        gm_builder = GMGraphBuilder(
            client=client,
            db_pool=db_pool,
            game_id=game.id
        )
        gm_graph = gm_builder.build()
        
        state = await prepare_gm_state(game, action)
        result = await gm_graph.ainvoke(state)
        
        narrative = result["narrative"]
        npc_updates = result["npc_updates"]
    else:
        # 旧：现有流程
        narrative = await generate_narrative(...)
        npc_updates = []
    
    # 解析和应用（完全相同）
    events = StreamingTagParser.parse(narrative)
    for event in events:
        await apply_tags(game, event)
    
    # NPC 更新也一样
    for update in npc_updates:
        await apply_npc_update(game, update)
    
    return {"narrative": narrative, "npc_updates": npc_updates}
```

---

## 6. Phase A（RAG）与 Phase B（LangGraph）的对比

| 维度 | Phase A（v0.4.0） | Phase B（v0.5.0） |
|-----|------------------|------------------|
| **问题** | 世界观太大，全文塞 Prompt 压力大 | 单 Agent 要做太多（规则、叙事、NPC、剧情），出错多 |
| **方案** | 向量化世界书，每回合动态检索 top-k 段落 | 拆成多个专职 Agent，用 LangGraph 编排 |
| **技术** | `langchain` + `chromadb` | `langgraph` + StateGraph |
| **实现范围** | 新增 `service/world_rag.py` | 新增 `service/gm_graph.py` |
| **影响范围** | `_build_key_facts()` 改为调 RAG 检索 | `run_turn()` 改为调 gm_graph.ainvoke() |
| **后向兼容** | 无（总是用 RAG） | 有（`use_graph` 设置，可选择开启） |
| **学到什么** | Embedding、向量数据库、检索增强 | 状态机、多 Agent 编排、条件分支 |
| **后续（Phase C）** | 数据收集：自动评测需要 RAG 的数据 | 数据收集：自动评测对比单 Agent vs 多 Agent |

### 可以同时使用吗？

**是的**。Phase A（RAG）是 `_build_key_facts()` 阶段，Phase B（LangGraph）是 `run_turn()` 阶段。独立工作：

```python
# 既用 RAG，也用 LangGraph
state = await prepare_gm_state(game, action)
# ↑ 这里已经调用 RAG 检索了

gm_graph = GMGraphBuilder(...).build()
result = await gm_graph.ainvoke(state)
# ↑ 规则预处理用 LangGraph
```

---

## 7. 执行效果

### 日志示例

```
[2026-05-03 14:22:30] use_graph=True, starting GM pipeline
[2026-05-03 14:22:31] rules_node: action_type=attack, requires_dice=true
[2026-05-03 14:22:32] dice_enrich: rolled d20, result=16
[2026-05-03 14:22:33] narrative_node: generating story (use_graph=true)
[2026-05-03 14:22:35] npc_react_node: found 2 NPCs in scene, 1 reacted in narrative, 1 missing
[2026-05-03 14:22:36] npc_react_node: supplementing NPC#42 reaction
[2026-05-03 14:22:37] GM pipeline complete: narrative=892 chars, npc_updates=1
```

### 与旧流程的对比

**旧流程（v0.4.0）**
```
⚠️  NPC#42 在场，但叙事中没有反应
⚠️  规则判定在流式文本中被遗漏
⚠️  单个 7B 模型同时判定 + 叙事，容易出错
```

**新流程（v0.5.0）**
```
✓ 规则 Agent 专注判定
✓ NPC Agent 专注补遗漏
✓ 叙事 Agent 专注创意
✓ 出错率显著降低
```

---

## 更新记录

- **v0.5.0** (2026-05-03)：LangGraph 多 Agent GM 实现
  - `service/gm_graph.py` — StateGraph 定义
  - `prompts/rules_template.py` — 规则判定 Prompt
  - `prompts/npc_react_template.py` — NPC 补充 Prompt
  - `use_graph` 会话设置（可选）
  - 完全向后兼容现有流程

