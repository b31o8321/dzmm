# dzmm 技术演进路线图

> 基于当前 v0.3.0 架构，按学习和功能价值排序。
> 每个阶段都在现有代码上扩展，不另开项目。

---

## 已完成

- **v0.3.0** — 场景节奏控制（scene_turn_count + 压力指令）
- **v0.3.0** — 骰子结果分支（success/fail 属性）
- **v0.3.0** — 弱模型适配（JSON 三级降级）
- **v0.4.0** — Phase A：LangChain RAG 世界书检索（OllamaEmbedder + ChromaDB + 自动重索引）
- **v0.5.0** — Phase B：LangGraph 多 Agent GM（StateGraph + 条件边 + NPC 后处理 Agent）

---

## Phase A — LangChain RAG：世界书检索

**问题：** 世界观全文塞进 Prompt，7B 模型上下文压力大，大型世界观写不下。

**方案：**
```
世界书 Markdown → 分块 → 向量化（embedding）→ 存向量库
每回合：当前场景 + 玩家行动 → 检索相关段落 → 只注入 top-k 块
```

**涉及技术：**
- `langchain` + `langchain-community`
- Embedding 模型（本地：`nomic-embed-text` via Ollama）
- 向量库（`ChromaDB`，本地文件，不需要额外服务）

**改动范围：**
- 新增 `service/world_rag.py` — 世界书向量化 + 检索
- 修改 `service/game.py` `_build_key_facts()` — 用检索结果替换全文注入
- 新增 `api/routes_worlds.py` — 触发世界书重新索引的接口

**学到什么：** RAG 完整流程、向量数据库、Embedding 模型

---

## Phase B — LangGraph：多 Agent GM

**问题：** 单个 LLM 既要做 RP 沉浸叙事，又要做规则判定、剧情宏观管理，对 7B 模型要求太高。

**方案：** 把 GM 拆成专职 Agent，LangGraph 编排协作流程：

```
玩家行动
    ↓
[规则 Agent]  ← 查 RAG 规则库，决定是否需要骰子判定
    ↓ (有判定)          ↓ (无判定)
[骰子工具]          [叙事 Agent]
    ↓                   ↑
[叙事 Agent] ← 综合判定结果生成沉浸叙事
    ↓
[NPC Agent] ← 每个在场 NPC 独立决定反应
    ↓
[剧情 Agent] ← 检查剧本进度，决定是否推进章节
    ↓
组合输出 → 现有 XML 标签格式 → 现有 apply_tags() 不变
```

**涉及技术：**
- `langgraph` — 有状态的 Agent 工作流
- LangChain Tools — 骰子、DB 查询封装成工具
- 现有 `ModelClient` 抽象继续复用

**改动范围：**
- 新增 `service/gm_graph.py` — LangGraph 定义的 GM 工作流
- `service/game.py` `run_turn()` 里替换 `build_gm_messages()` 调用
- 现有 `parsing/`、`state_apply/`、API 层**完全不动**

**学到什么：** LangGraph 状态机、多 Agent 编排、Tool calling

---

## Phase C — 自主 Agent：自动评测

**问题：** 怎么知道 Phase B 的多 Agent GM 比现在的单 GM 好？需要量化评测。

**方案：** 两个自主 Agent 跑自动对局：

```
[玩家 Agent]                    [评审 Agent]
  - 扮演玩家，随机/策略性行动       - 旁观整局对话
  - 自主决定下一步做什么            - 每 10 回合打分：
                                      · 剧情推进速度
                                      · 铁律违反次数
                                      · RP 沉浸感（LLM 主观评分）
                                      · 骰子规则准确性
```

跑 N 局，输出对比报告：单 GM vs 多 Agent GM。

**涉及技术：**
- AutoGen 或 LangGraph 多 Agent 对话
- 评分 Prompt 设计
- 结果写入 `feedbacks` 表（现有表可复用）

**学到什么：** 自主多 Agent、LLM-as-Judge 评测模式

---

## Phase D — 微调（可选，需要台式 Linux）

**问题：** Phase B 用多 Agent 规避了单模型能力不足，但增加了延迟和复杂度。根本解法是训一个既懂 RP 又懂 GM 脑的模型。

**方案：**
- 用 Phase C 的自动评测跑出大量 (场景, GM输出, 评分) 数据
- 筛出高分样本作为 SFT 训练集
- 用 QLoRA 微调 Qwen2.5-7B
- 评测：微调后的单 Agent 能否达到 Phase B 多 Agent 的效果？

**硬件：** 台式 RX 9070 (16G VRAM) + Linux + ROCm

---

## 开始顺序建议

```
现在可以开始 → Phase A（RAG）
  需要先学 LangGraph → Phase B
  Phase B 跑起来后 → Phase C（数据自然产生）
  有足够数据 → Phase D（台式机）
```

Phase A 是独立的，随时可以开始，不影响现有功能。
