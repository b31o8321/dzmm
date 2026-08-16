# ADR-003：在版本化世界聚合上扩展叙事规则集

**状态：** Accepted
**日期：** 2026-08-17
**决策人：** DZMM 产品负责人、工程负责人

## Context

vNext 已采用 `World → WorldVersion → Run → RunState → Turn[]` 作为单一版本化聚合，并用 Python command 作为状态裁判。产品定位现升级为“本地优先、状态驱动的互动叙事平台”：除 TRPG 外，还需支持章节分支、角色关系和多结局。

外部内容生态已广泛使用 World Info/Lorebook 与 Character Card。将其改名为私有的“知识实体”或“人物模板”会增加理解和导入成本；但直接执行 World Info 的 regex/script 又会破坏 Python-first 的状态边界。

## Decision

1. 在既有、不可变的 `WorldVersion.definition` 中加入受限的 `ruleset`、章节、选择、关系事件、Flag 与 ending definitions；不创建 Story、Route、Relationship 等新的存档根或 API 生命周期。
2. `Run` 创建时固定 `world_version_id` 与 `ruleset_id`。所有可变章节、路线、Flags、关系、资源、TRPG 状态和 ending 都写入唯一 revisioned `RunState`；所有改变都有一个审计 `Turn`。
3. `TurnCommand` 只能由 Python 验证/生成并以白名单应用。LLM 只产生无写权限的 `NarrativeIntent`；玩家仅提交动作或当前可选 choice，不能提交任意 command payload。
4. 使用用户和互通层通用术语：**世界书（Lorebook / World Info）**、**角色卡（Character Card）**。它们是 DZMM 的一级、可版本化内容资产，而非一次性导入结果或 DZMM 私有概念的别名。`WorldDefinition` 是内部 JSON contract 名称；世界书是上下文知识层，角色卡是内容输入，二者不直接写 RunState。公开 contract、UI 和导入/导出报告采用 `lorebook` / `character_cards`；不冻结 `lore`、`人物模板` 等中间术语。
5. `hybrid` 是显式 capability 组合，不是“所有 command 默认开放”。规则集只允许其 definition 声明的 command、状态字段和跨域桥接。

```text
World
  └─ WorldVersion (immutable WorldDefinition + ruleset)
       ├─ 世界书 / Lorebook           context-only, interoperable
       ├─ 角色卡 / Character Card     content source, interoperable
       └─ chapter / relation / ending definitions
            └─ Run (fixed world version + ruleset)
                 ├─ RunState (all mutable facts, revisioned)
                 └─ Turn[] (narrative + validated commands + snapshots)
```

## Options considered

### A. 在既有聚合上扩展受限叙事规则集（采用）

| 维度 | 评估 |
|---|---|
| 领域一致性 | 高 |
| 存档/回滚复杂度 | 中，可复用已有边界 |
| 用户心智负担 | 低 |
| 安全与可解释性 | 高 |

优点：一套创建、删除、回滚、Android 恢复和审计语义；TRPG、剧情和关系可在 `hybrid` 中安全组合。
代价：需要升级 schema、引擎、UI 和成熟度基线，不能把已有 TRPG 测试直接当剧情能力证据。

### B. 新建剧情/恋爱存档模型与第二套 UI

| 维度 | 评估 |
|---|---|
| 领域一致性 | 低 |
| 存档/回滚复杂度 | 高 |
| 用户心智负担 | 高 |
| 安全与可解释性 | 中 |

优点：短期可快速做出单一 Galgame 原型。
缺点：重现 v0.x 的多级关联、删除不净和运行态漂移；手机还需判断连接的是哪种存档。

**结论：拒绝。**

### C. 允许世界书脚本或 LLM 自由修改 JSON

| 维度 | 评估 |
|---|---|
| 作者自由度 | 高 |
| 可审计性 | 低 |
| 状态安全 | 低 |
| 模型/格式互通 | 表面高，实际不可控 |

优点：看似接近酒馆的灵活性。
缺点：无法证明关系、Flag 和结局的来源，也无法可靠回滚或防止模型刷数值。

**结论：拒绝。**

## Consequences

- 现有 vNext JSON schemas 将在 Phase 0 升级到 v2；在此之前不半实现新字段，避免运行态和文档假设不一致。
- World Info 的未知字段继续 escrow；只映射确定性知识字段。角色卡/世界书导入、提升、编辑、导出是 WorldVersion authoring 行为，不是 Run 行为。导入角色卡必须持久保存卡及其原始 payload；仅将其降级为“建议主角”不算完成角色卡互通。
- 结局由 Python 的有限条件树与稳定优先级确定；LLM 可接收并叙述“已锁定的 ending”，不能推断真实 ending。
- 关系变化将从“任意 number delta”变为“已定义 relationship event 的固定 effect + reason + once/cooldown ledger”。这限制作者的随意脚本，但换来可解释和可重放。
- Android contract 需增加可见 chapter/choice/relationship/ending projection，却不能获得 ruleset authoring、模型或生命周期权限。

## Action items

1. [ ] 批准规格中的术语、雾港 vertical slice 和开放项。
2. [ ] 升级 v2 contracts，并为 ruleset 越权、非法 command、关系事件、ending priority 写 schema/engine tests。
3. [ ] 实现雾港 deterministic fixture 和 Mac journey，再接 Huihui 14B 真实模型验证。
4. [ ] 在 scorecard 中替换平台矩阵，标记旧 58.0 为不可横比的前序基线。
5. [ ] 最后才迁入 TRPG capabilities 并实现 hybrid；不创建第二存档模型。
6. [ ] 将公开 `lore` contract/API/UI 替换为 `lorebook`，实现角色卡持久化、V3 JSON/PNG metadata 导入与保真导出 round-trip。
