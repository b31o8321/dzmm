# ADR-004：以世界书和角色卡作为一等互通内容，而非 DZMM 私有替代物

**状态：** Accepted  
**日期：** 2026-08-17  
**决策人：** DZMM 产品负责人、工程负责人

## Context

DZMM vNext 的目标不是做一个只会导入外部文本的 TRPG 壳，而是让作者能够直接拥有、使用和带走
**世界书（Lorebook / World Info）**与**角色卡（Character Card）**。这些是当前互动叙事/RP
生态已经形成的用户心智和互通边界；以“知识实体”“人物模板”等私有名称替代，会让导入、创作、
搜索和交流都多一层无意义翻译。

当前 v2 vertical slice 已采用 `lorebook` 与 `character_cards` 的公开名称，但仍把
`relationship_dimensions` 放进 `character_cards[]`。这会把一张可移植的角色卡误当成某个世界中的
关系规则：同一张卡不能在两个世界有不同关系设计，也容易让人误以为卡内文字/字段可以改变
RunState。这一边界需要在下一轮 contract 重构前冻结。

## Decision

1. DZMM 的稳定用户/API 概念固定为：世界书、世界书条目、角色卡、角色卡引用、关系定义、章节、
   Flag、路线和结局。`WorldDefinition`、`RunState`、`TurnCommand` 仅为内部技术 contract 名称，
   不能取代这些产品概念。
2. `lorebook` 与 `character_cards` 是 `WorldVersion` 的一等、不可变内容快照：可新建、导入、预览、
   编辑后生成新版本、导出。SillyTavern World Info 与 V3 JSON/PNG 为优先互通格式；原始未知字段
   escrow 保留，绝不执行。
3. 角色卡只承载角色身份和叙事内容（例如 name、description、personality、scenario、first message、
   example dialogue、character book、来源与原始 payload）。**不得**承载好感/信任初值、关系数值范围、
   路线资格、Flag writer 或结局条件。
4. 一个世界要让某张卡成为可互动对象，必须在该 WorldVersion 的 `story.relationships[]` 中显式建立
   `RelationshipDefinition`，以 `character_card_id` 引用卡，并在这里定义 dimensions、初值、范围、
   可见性和路线资格。`relationship_events[]` 改为引用 `relationship_id`；`RunState.relationships`
   以 relationship ID 为键。Python 只接受由这些定义触发的固定事件，不接受通用数值写入。
5. 地点/NPC/资源等结构化世界事实与角色卡之间也只允许稳定 ID 引用，禁止按名称或由模型猜测绑定。
   Mac 世界中心应展示“角色卡”及其在本版本的场景/关系引用；Android 只显示当前 Run 已投影出的角色、
   关系和结局，不提供作者管理权。

```text
WorldVersion
  ├─ Lorebook / World Info                 可互通上下文，不能写状态
  ├─ Character Cards                       可互通角色内容，不能含关系真值
  └─ Narrative Ruleset
       ├─ RelationshipDefinition ────────> CharacterCard (stable ID)
       ├─ Chapter / Choice / Flag / Route
       └─ EndingDefinition
            └─ RunState.relationships     Python command 的可变结果与审计
```

## Options considered

### A. 通用内容资产 + 显式规则引用（采用）

| 维度 | 评估 |
|---|---|
| 生态互通 | 高 |
| 作者可理解性 | 高 |
| Python 状态边界 | 高 |
| Contract 重构成本 | 中 |

优点：外部卡可以原样保真并在不同世界以不同关系规则复用；关系和结局的来源可审计。
代价：必须把当前 v2 卡内关系字段迁到 ruleset，并重新验证雾港切片。

### B. 继续让角色卡携带关系维度

优点：短期 fixture 较少字段。
缺点：把可移植内容与世界特定规则耦合，背离社区语义，也使一个角色在多世界/多路线下难以解释。

**结论：拒绝。**

### C. 只做导入器，内部仍使用 DZMM 私有“人物模板/知识实体”

优点：内部模型表面统一。
缺点：用户看不见、带不走，也无法清楚知道哪些外部字段被保留或生效。

**结论：拒绝。**

## Consequences

- 下一版 clean-slate contract 应升为 schema v3；不提供 v2 兼容/迁移。当前 v2 的确定性雾港行为可作
  引擎参考，但不能作为新内容边界的完成证据。
- `CharacterCard` 删除 `relationship_dimensions`；新增 `RelationshipDefinition`（含
  `id`、`character_card_id`、`dimensions`、`initial_values`、`bounds`、`visibility` 与可选 route binding）。
  `RelationshipEvent` 从 `character_card_id` 改为 `relationship_id`。
- 先完成角色卡编辑/显式引用 UI，再把“卡转建议主角”降为可选创建辅助；它绝不能取代角色卡的持久化。
- 不新建第二套内容/存档根。内容库如被实现，只是作者的可复用目录；Run 仍固定引用 WorldVersion 内的
  content snapshot，删除、回滚和导出仍由 World 聚合拥有。

## Action items

1. [ ] 将 schema、fixture、引擎和 API 中角色卡内的关系字段迁入 `story.relationships[]`，并拒绝旧字段。
2. [ ] 为“同一张卡在两个 WorldVersion 的不同关系配置”“关系 event 引用不存在 target”“LLM/客户端
      直接写 relationship state”增加 contract 和 engine tests。
3. [ ] 在世界中心补角色卡编辑、引用面板和导入/导出兼容报告；用打包桌面应用完成一次真实 PNG round-trip。
4. [ ] 以 schema v3 重新取得雾港的四类结局、回滚、重开和真实模型证据；再进入 TRPG/hybrid 扩展。
