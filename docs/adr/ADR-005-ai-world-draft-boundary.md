# ADR-005：AI 世界创作只产生可审阅的受限草案

**状态：** Accepted  
**日期：** 2026-08-17  
**决策人：** DZMM 产品负责人、工程负责人

## Context

vNext 已把所有真实玩法状态收敛到 `World → WorldVersion → Run → RunState → Turn[]`，并由
Python command 裁判。用户还需要从自己的题材想法生成随机世界，而不只导入外部分享内容。
若模型可以直接创建世界或自由产生 command，便会重新引入不可审计的第二写入路径。

## Decision

模型只生成瞬时 `WorldDraft`：一个 schema v3 `WorldDefinition` 候选、Hero 候选与解释性
repair/validation 报告。草案不持久化、不占用 World 生命周期、不改变任何真实状态。Mac 用户审阅、
编辑并通过后，唯一的写路径仍是现有原子 `WorldComposer.compose`。

模型受限于一个 JSON-only prompt 和既有 ModelProfile 协议。后端先确定性提取单个 JSON，再执行
schema 与 narrative semantic validation。格式围栏和缺失 schema version 可以明确修复；任何
未知字段、任意 command、脚本、正则、无效 effect、关系/ending 引用错误都被拒绝，而不是让模型
“自动修好”。原生生成角色卡使用受控 mapper 导出 SillyTavern V3；世界书仍按 World Info 安全 mapper
导出。

## Options considered

### A. 瞬时受限草案 + 既有 compose（采用）

优点：无第二存档根，确认前零 DB 写入，用户仍拥有最终编辑权，Python-first state boundary 完整。
代价：Host 重启不恢复未确认草案，首次自由题材生成受 schema 能力限制。

### B. AI 直接创建 World/Run

优点：表面上更快。
缺点：模型失败/重试会产生半成品，无法证明用户确认、幂等和状态来源。

**结论：拒绝。**

### C. 保存 Draft 表并建立 Draft lifecycle

优点：可跨重启恢复。
缺点：新增第二个世界根、归档/删除/权限语义和迁移负担，不是首版用户价值的必要条件。

**结论：首版拒绝。**

## Consequences

- 新端点只属于 API v2 / loopback Mac authoring surface；移动端不获得创作权限。
- 生成和编辑的候选必须是当前 schema v3，不提供 v2 或 legacy adapter。
- `WorldComposer` 无需知道 AI；它只校验并原子 compose 用户最终确认的 payload。
- 成熟度矩阵新增 AI 创作验收证据，但当前分数不变，直到真实模型和打包桌面 journey 通过。

## Action items

1. [x] 实现 Draft request/result、模型 JSON generator、extract/repair/validate service 与失败测试。
2. [x] 为原生生成角色卡提供 SillyTavern V3 导出 mapper。
3. [x] 实现 Mac 审阅/编辑/验证/确认/取消 UX，确认重用 compose 幂等性。
4. [x] 用 Huihui 14B 完成雾港复杂度真实旅程，更新 Active Delivery Index 与评分证据。
