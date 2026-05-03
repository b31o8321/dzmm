# Phase C：自主 Agent 自动评测

> 本文对应 `eval/` 目录，讲解 LLM-as-Judge 评测模式和自主 Agent 编排。

---

## 1. 为什么需要自动评测

Phase B 添加了多 Agent GM，但怎么知道它比单体 GM 好？需要量化评测：

- **规则匹配**（是否遵守铁律）：过于机械，无法评估叙事质量
- **人工评测**：准确但昂贵、慢，无法大规模运行
- **LLM-as-Judge**：用 LLM 评估另一个 LLM 的输出 → 自动化、可扩展、比规则灵活

---

## 2. 三个 Agent 的分工

```
[玩家 Agent]              [评审 Agent]
  对话历史 → LLM           每 10 回合旁观评分
  → 下一步行动               plot_speed / rule_violations
                             rp_immersion / dice_accuracy
         ↕
[GM（已有系统）]
  处理行动 → 叙事 + 事件
```

---

## 3. 玩家 Agent

`eval/player_agent.py`：

```python
async def generate_player_action(messages, character_md, character_name, client):
    pairs = [(msg.content, next_msg.content) for ...]
    prompt_msgs = build_player_messages(character_name, character_md, pairs)
    action, _ = await client.complete(prompt_msgs, GenerationParams(temperature=0.8))
    return action
```

**感知（Perceive）→ 思考（Think）→ 行动（Act）** — Agent 的基本循环。
`temperature=0.8` 保证每次行动都有随机性（不会陷入重复循环）。

---

## 4. LLM-as-Judge 评审 Agent

`eval/judge_agent.py`：

```python
@dataclass
class EvalScore:
    plot_speed: float       # 剧情推进速度 0-10
    rule_violations: int    # 铁律违反次数（越少越好）
    rp_immersion: float     # RP 沉浸感 0-10
    dice_accuracy: float    # 骰子规则准确性 0-10

    @property
    def overall(self) -> float:
        return (plot_speed + max(0, 10 - violations*2) + rp_immersion + dice_accuracy) / 4
```

评审 LLM 被要求输出严格 JSON，用三级解析保证鲁棒性：
1. 直接 `json.loads(raw)`
2. 正则提取 `{...}` 块
3. 失败 → 返回默认分（5.0）

---

## 5. 评测编排器

`eval/runner.py`：

```python
for turn_num in range(1, config.max_turns + 1):
    # 1. 玩家 Agent 生成行动
    action = await generate_player_action(recent_msgs, char_md, char_name, player_client)
    # 2. GM 处理回合
    async for _ in run_turn(s, session_id, action, gm_client):
        pass  # 评测时丢弃流式事件
    await s.commit()
    # 3. 每 N 回合评审
    if turn_num % config.judge_every == 0:
        score = await judge_session(...)
        scores.append(score)
```

**关键：** `async for _ in run_turn(...)` 消耗整个 async generator 但丢弃事件。
这是让 `run_turn()` 在"静默模式"下运行的惯用写法。

---

## 6. Phase A/B/C 技术对比

| | Phase A (RAG) | Phase B (LangGraph) | Phase C (Agent Eval) |
|-|---------------|---------------------|----------------------|
| 解决的问题 | 世界书太长 | 单模型能力瓶颈 | 如何量化评测质量 |
| 核心模式 | 检索增强生成 | 有状态工作流 | LLM-as-Judge + 自主 Agent |
| Agent 数量 | 1（嵌入器） | 3（规则/叙事/NPC） | 3（玩家/GM/评审） |
| 时间维度 | 单回合内 | 单回合内 | 跨多回合（宏观编排） |
| 输出形式 | 更好的 Prompt | 更好的叙事 | 量化质量报告 |
