# ADR-012: Director 轻量长线节奏注入

**Status:** Accepted
**Date:** 2026-09-06
**Deciders:** 产品与维护者
**关联:** [ADR-010 单一 DZMM 受控替换](ADR-010-single-dzmm-cutover.md)、旧版 `service/agents/director` 的吸收

## Context

旧版维护一条 LangGraph 多 Agent 链（Director 每 5 回合做长线决策，Scene 出叙事）。
单线化的 vNext/dzmm 采用单次 GM 调用 + 确定性 story beat 投影，长线压力目前来自
`narrative_variation`：从世界素材（事件/NPC/地点/世界书标签）里按回合哈希**确定性轮换**
一条压力提示。它的弱点是"有压力但无记忆"——不追踪跨回合的张力走向，也不理解
玩家最近实际经历了什么。

## Decision

吸收旧版 Director 的**职责**（长线节奏与钩子），不移植其编排：

1. **触发**：每 `DIRECTOR_INTERVAL = 6` 个已提交回合，在回合成功落库后由后台
   daemon 线程异步执行一次 Director 调用（不在回合关键路径上，回合耗时零增加）。
2. **调用**：复用该 Run 的模型档案，走新增的 `request_director_note`（低温度、
   小 num_predict、严格 JSON system prompt），输入为最近 6 回合摘要 + 活跃
   剧情线 + 当前章节。
3. **输出契约**：仅接受 `{"tension": str, "hook": str}`，字段白名单、长度截断
   （各 ≤120 字符）；解析失败或调用失败一律**静默丢弃**。
4. **存储**：新表 `director_notes(run_id, turn, tension, hook)`（迁移 0013）。
   不进入 `run_state`（契约 additionalProperties=false 保持不变）。
5. **消费**：GM 的叙事请求 payload 增加 `director_note` 字段——仅当存在
   `turn >= 当前回合 - 2*INTERVAL` 的记录时注入；提示词把它标注为"长线节奏参考，
   非硬性指令"。
6. **降级**：任何失败（无模型档案、超时、非法输出）= 该周期没有 Director 注释，
   GM 照常出回合，行为与现状完全一致。

## Options Considered

| 方案 | 评估 | 结论 |
|---|---|---|
| A. 移植旧版 LangGraph Director/Scene 编排 | 引入多 Agent 框架与每回合多次模型调用，与薄壳架构冲突 | 否决 |
| B. 同步 Director 调用（回合内阻塞） | 回合延迟翻倍，违反 <15% 耗时预算 | 否决 |
| C. 后台线程异步摘要 + 下一周期消费（本 ADR） | 零关键路径开销、失败即降级、与单 GM 兼容 | **采用** |

## Consequences

- Director 注释永远滞后最多一个周期——它影响"接下来几回合的走向"，不影响当前回合。
- 单测可以用脚本化 FakeClient 同时扮演 GM 与 Director，分别断言两类请求。
- 若实测显示 Director 注释质量差或玩家无感，可直接停用调度（一处布尔），无迁移负担。
