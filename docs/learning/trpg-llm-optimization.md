# TRPG 场景的 LLM 优化策略

> 本文记录 TRPG 场景的特殊挑战，以及 dzmm 项目中针对每个挑战的落地方案。
> 这些决策都有具体的代码对应，不是空谈。

---

## 1. TRPG 的特殊性

TRPG（桌游跑团）对 GM LLM 的要求，和普通对话 AI 有本质区别：

| 维度 | 普通对话 AI | TRPG GM |
|------|------------|---------|
| 上下文长度 | 单轮 Q&A | 几十回合连续叙事，需要记住所有细节 |
| 输出格式 | 自由文本 | 必须同时产出叙事文本 + 结构化事件（骰子/NPC/道具）|
| 规则约束 | 无 | 铁律系统：某些行为绝对禁止 |
| 随机性 | 固定逻辑 | 骰子 = 真实随机，LLM 倾向于假装扔骰子 |
| 一致性 | 无需跨轮一致 | NPC 性格/世界状态必须跨几十回合一致 |
| 创意与规则的张力 | 无 | 好叙事 vs 遵守规则，两者经常冲突 |
| 实时性 | 用户可以等 | 玩家期待打字机效果，延迟超过 3 秒体验变差 |

这七个特性，每一个都对应一个工程问题。

---

## 2. 长上下文问题 → RAG 世界书（Phase A）

### 问题

TRPG 世界书往往有几千字：地理、历史、NPC 列表、规则集。如果每回合都把完整世界书塞进 prompt，有两个代价：
1. **成本**：输入 token 贵，且上下文越长模型越容易"遗忘"后面的内容
2. **注意力稀释**：LLM 注意力有限，无关内容会挤占关键信息的权重

### 方案

**RAG（Retrieval-Augmented Generation）**：把世界书向量化，每回合只检索与当前玩家行动最相关的段落。

```
世界书（Markdown） → 分块（RecursiveCharacterTextSplitter）
                  → 嵌入（OllamaEmbedder / nomic-embed-text）
                  → 存入 ChromaDB（本地向量库）

每回合：
  玩家行动 → 嵌入 → 在 ChromaDB 中找 top-k 相关段落
  → 只把这 k 段塞进 GM prompt
```

**关键实现细节** — `service/world_rag.py`：

```python
def get_world_md(world_id, content_md, query, ollama_url, model, k, _embedder, app_dir) -> str:
    # 四个 fallback，保证 RAG 永远不会让游戏崩溃
    if not ollama_url:          return content_md  # Ollama 未配置 → 全文
    if len(content_md) < 800:   return content_md  # 世界书太短 → 不值得检索
    if not is_indexed(world_id): return content_md  # 未建索引 → 全文
    return retrieve_world_context(...)              # 正常 RAG
```

**三级降级**是关键设计原则：新功能不能让已有游戏崩溃。

---

## 3. 单模型能力瓶颈 → LangGraph 多 Agent GM（Phase B）

### 问题

单个 LLM 在一次请求里要同时做：
1. 规则裁判（当前行动触发什么检定？DC 是多少？）
2. 叙事写作（流畅、有代入感的叙述）
3. NPC 状态更新（说了什么话、情绪如何变化）

这三件事风格完全不同——规则分析要精确，叙事要有创意，NPC 反应要有个性。要求一个 LLM 同时做好三件事，等于让一个人同时当裁判、导演和演员。

### 方案

**LangGraph 有状态工作流**：三个 Agent 分工，每个只专注一件事。

```
用户行动
  ↓
[Rules Node] → 分析行动类型 + 检定需求（精确，temperature=0.2）
  ↓ （如果有检定 DC）
[Dice Enrich Node] → 标注骰子预告（纯文本处理，不调 LLM）
  ↓
[Streaming Narrative] → 正式叙事（保持不变的流式输出路径）
  ↓
[NPC Post-pass Node] → NPC 对话/状态补充（个性化，temperature=0.7）
```

**关键实现** — `service/gm_graph.py`：

```python
# 条件路由：只有检测到骰子检定时才走 dice_enrich 分支
def _route_after_rules(state: PrePassState) -> str:
    enrichment = state.get("rules_enrichment", "")
    if "检定" in enrichment and "DC" in enrichment:
        return "dice_enrich"
    return END

# 闭包注入 ModelClient（LangGraph 节点签名固定为 f(state)->dict）
def make_rules_node(client: ModelClient):
    async def rules_node(state: PrePassState) -> PrePassState:
        output, _ = await client.complete(msgs, _RULES_PARAMS)
        return {**state, "rules_enrichment": output.strip()}
    return rules_node
```

**为什么闭包注入**：LangGraph 节点的签名是 `async def f(state: S) -> S`，不能接受额外参数。用工厂函数把 `ModelClient` 捕获到闭包里，是标准解法。

**向后兼容**：通过 `session.settings_json` 中的 `use_graph` 开关，老会话不受影响：

```python
settings = json.loads(sess.settings_json or "{}")
if settings.get("use_graph"):
    key_facts = await run_pre_pass(key_facts, user_action, client)
elif settings.get("director_pass"):
    # 旧逻辑保留
```

---

## 4. 规则约束问题 → 铁律系统（Prompt Engineering）

### 问题

LLM 倾向于"皆大欢喜"——它会让玩家成功、不会真正惩罚失败、不会让 NPC 死去。这对 TRPG 是致命的：失去了风险，游戏就没有张力。

### 方案

**铁律**：在 System Prompt 中用强约束语言写死的规则，不给 LLM 回旋余地。

不好的写法（软约束，LLM 会找借口绕过）：
```
请尽量根据骰子结果来决定行动是否成功
```

好的写法（硬约束，铁律措辞）：
```
铁律 1【绝对执行，无例外】骰子 ≤ DC 时，行动必须失败，且失败要有实质后果。
"虽然失败了但是…" = 严重违规。
```

从 v0.2.2 实装的关键铁律（截至本文）：
- **骰子结果不可篡改**：失败就是失败，不得用"努力总算没白费"之类话语掩盖
- **剧情不得停滞**：每 3 回合内必须有一件新鲜事（不能反复描述同一场景）
- **NPC 不能无限包容**：NPC 有自己的利益和底线，玩家的无理行为会有后果
- **骰子检定前必须声明 DC**：避免 GM 事后调整 DC 以迁就结果

**技术实现**：铁律在 `service/game.py` 的 `_build_key_facts()` 里注入到每回合的 prompt context 里。数量从 v0.2.x 的 20 条逐步增加到 27 条。

---

## 5. 骰子真实随机 → Dice Monitor + 前端拦截

### 问题

LLM 无法产生真实随机数。如果让 GM 自己"扔骰子"，它会根据剧情需要选择对玩家有利的结果（确认偏差）。

### 方案

**前端生成骰子，GM 接受结果**：

1. 玩家行动触发检定时，前端用 `Math.random()` 生成真实骰子值
2. 骰子结果附加在玩家消息里传给后端
3. GM 的铁律明确要求：收到骰子结果后必须接受，不得改变

这样 GM 只负责"解释结果"，不负责"产生结果"，从架构上杜绝了骰子作弊。

**Dice Enrich Node**（Phase B）：Rules Agent 分析出需要骰子检定时，在叙事之前插入一段标注，提示 GM 这一回合有骰子检定、DC 是多少。这相当于给 GM 一个"提词器"，避免它在叙事中忘记骰子的存在。

---

## 6. 结构化输出 → 流式 XML 解析

### 问题

GM 的回应不只是纯文本——它需要同时触发游戏事件：骰子检定、道具获取、NPC 状态变化、剧情里程碑。这些事件需要写入数据库，纯文本无法满足。

但如果用 JSON 输出，流式传输就会破坏格式（因为 JSON 在闭合 `}` 之前不完整）。

### 方案

**XML Tag 流式解析**：用自闭合/配对标签包裹结构化信息，可以在流式输出中逐 token 解析：

```
GM 输出（流式）：
你走进了昏暗的房间。<dice sides=20 dc=15/>
角落里坐着一个陌生人，他抬头看了你一眼。<npc_update name="陌生人">警觉，右手
悄悄移向腰间。</npc_update>
<plot_event>玩家进入酒馆，与神秘人首次接触</plot_event>
```

**StreamingTagParser** — `parsing/stream_parser.py`：
- 维护一个字符缓冲区，逐 token 检测标签的开始和结束
- 检测到完整标签时 yield `ParseEvent`（带标签名和内容）
- 文本内容实时 yield `ParseEvent(type="text", content=chunk)`，不等标签结束

这个设计保证了：叙事文字实时推送给前端（低延迟），事件标签在完整后才处理（正确性）。

---

## 7. LLM 格式不稳定 → 三级 JSON 解析

### 问题

要求 LLM 输出严格 JSON 时，它有时会：
- 在 JSON 前后加说明文字（"以下是评分结果：{...}"）
- 用中文冒号（`：`）代替英文（`:`）
- 输出截断的不完整 JSON

任何一种情况都会让 `json.loads()` 直接崩溃。

### 方案

**三级解析**（在 `eval/judge_agent.py` 和其他地方都用了这个模式）：

```python
def _parse_judge_output(raw: str) -> dict:
    # 级别 1：直接解析（正常情况）
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        pass
    # 级别 2：正则提取第一个 {...} 块（有前后废话）
    m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except (ValueError, TypeError):
            pass
    # 级别 3：抛出异常，由调用方 fallback 到默认值
    raise ValueError(f"no parseable JSON: {raw[:200]}")
```

调用方捕获异常，返回默认值，游戏继续。**永远不让格式问题崩溃整局游戏。**

---

## 8. 实时性要求 → 流式输出架构

### 问题

本地 Ollama 模型生成速度约 10-30 token/秒，生成一段完整叙事需要 5-15 秒。用户等待空白界面体验很差。

### 方案

**SSE（Server-Sent Events）流式推送**：

```
后端 run_turn() → 边生成边 yield SSE 帧
    ↓
前端 useGameTurn.ts → EventSource 接收
    ↓
每收到一帧文字立即渲染（打字机效果）
```

**关键约束**：LangGraph 节点（Rules / NPC）用 `client.complete()`（等待完整响应），不用流式，因为它们只负责 prompt 增强，不直接面向用户。叙事 GM 用 `client.stream()`，因为它的输出要实时展示。

**延迟预算分配**：
- Rules Node（pre-pass）：< 1 秒（短 prompt，temperature=0.2）
- Streaming Narrative：打字机实时渲染
- NPC Post-pass：叙事结束后额外追加，用户已经看到叙事，等感低

---

## 9. 上下文窗口管理

### 问题

对话历史会无限增长，超过模型上下文窗口（Ollama 本地模型通常 4K-8K）后，早期信息被截断，GM 会"失忆"。

### 当前策略（截至 v0.6.0）

在 `service/game.py` 的 `_build_messages()` 里：
- 只取最近 N 回合的对话历史（而非全部）
- 关键信息（世界书摘要、人物卡）放在 system message（更高优先级）
- 通过 RAG（Phase A）按需注入世界书，不占固定空间

**待改进**（Phase D 的方向）：训练模型做"重要事件压缩"，把 N 回合的历史摘要成关键事实，再传给 GM。

---

## 10. 综合：各问题与方案的对应关系

| TRPG 特殊问题 | 根本原因 | 落地方案 | 代码位置 |
|--------------|---------|---------|---------|
| 世界书太长 | 上下文窗口有限 | RAG 按需检索 | `service/world_rag.py` |
| 单模型能力瓶颈 | 一个 LLM 难以同时擅长规则+叙事+角色 | LangGraph 多 Agent 分工 | `service/gm_graph.py` |
| GM 绕过规则 | LLM 倾向讨好用户 | 铁律硬约束 | `service/game.py` key_facts |
| 骰子作弊 | LLM 无法产生真随机 | 前端掷骰，GM 只接受结果 | 前端 + 铁律 |
| 结构化事件 + 流式文本 | JSON 不支持流式 | XML Tag 流式解析 | `parsing/stream_parser.py` |
| JSON 格式不稳定 | LLM 经常输出噪音 | 三级解析 + 默认 fallback | `eval/judge_agent.py` |
| 生成延迟 | 本地模型慢 | SSE 流式 + 打字机渲染 | `service/game.py` + 前端 |
| 质量无法量化 | 人工评测太慢 | LLM-as-Judge 自动评测 | `eval/` 全目录 |
