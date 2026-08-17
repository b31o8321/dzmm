# DZMM vNext AI 世界创作向导

**状态：** Approved for the first vertical slice  
**日期：** 2026-08-17  
**范围：** vNext API v2、Mac 创作向导、schema v3；不读取旧版数据或 API。

## 问题与目标

现有 vNext 可以导入和编辑他人分享的世界书、World Info 与角色卡，但新玩家还不能从一个
题材想法安全地得到可玩的世界。目标是把本地模型变成**创作草案员**：用户填写题材、基调、
核心冲突、主角偏好和可选角色偏好，获得可审阅的剧情冒险、关系叙事或 hybrid 草案。

成功不是模型“自动开局”，而是用户能在 Mac 上完成：一键草案 → 审阅/编辑 → 明确确认 →
原子创建 → 三个 Python choice 回合 → 可见结局 → 回滚。首个验收以雾港同等复杂度为下限。

## 产品范围

### P0

1. 仅由已配置的 vNext `ModelProfile` 生成草案；模型档案是完整的 provider/base URL/model
   协议配置，不能把模型名写入另一种协议配置。
2. `POST /api/v2/ai-world-drafts:generate` 只返回内存中的 `WorldDraft`；它**不写数据库**，
   不创建 World、WorldVersion、Hero、Run 或 RunState。
3. 输入含题材、基调、核心冲突、主角偏好、0–4 个角色偏好和目标 ruleset
   (`story_adventure`、`relationship_drama` 或 `hybrid`)；模型只产生受限创意内容源，Python
   将其投影为完整 schema v3 `WorldDefinition` 与 Hero 草案。
4. 后端从模型响应中只提取一个 JSON 创意候选，并使用严格 source schema、WorldDefinition JSON
   schema 和 `validate_definition` 三重校验。仅可做确定性、可显示的格式修复（例如移除 Markdown
   代码围栏）；语义/ID/未知字段/command 违法一律拒绝，并返回路径化错误。不得做“猜测式”修复。
5. 生成的角色写入 `character_cards` 一级资产；原生卡由受控 mapper 导出为 SillyTavern V3。
   生成设定写入 `lorebook` 一级资产并可导出为 World Info。
6. 剧情草案至少具备 3 章、每章可选 choices、Flag、显式 RelationshipDefinition、固定
   relationship events、routes 和多种 EndingDefinition。choices 的 effect 只能是 schema
   白名单中的 Python 预定义 effect；不存在 `commands`、脚本、正则或 Python 字段。
7. Mac 向导展示 brief、章节、角色卡/关系、世界书与 endings，并提供受校验的 JSON 编辑区。
   用户按“验证编辑”后才可启用“确认并创建世界”；确认仍调用现有
   `POST /api/v2/worlds:compose`，使用每次确认稳定的 request ID。
8. 空输出、模型/网络失败、无法解析 JSON、schema/语义无效、用户取消、编辑后无效和重复确认
   都有可恢复 UX；取消只丢弃前端草案，不产生数据库行。

### 非目标

- 模型不执行任意 Python、JavaScript、世界书 regex、prompt script 或任意 TurnCommand。
- 不让模型直接持久化、修改 RunState、关系数值、Flag、章节、路线或结局。
- 不新增 Draft/Story/Relationship 的数据库根，不做旧存档、旧 API 或旧 UI 兼容。
- 首版不做无限自由题材的自动质量承诺、后台队列、云生成或 Android 创作；Android 仍是
  gameplay-only。

## 领域与 API 决策

```text
AI World Brief + ModelProfile
        │
        ▼
ephemeral WorldDraft { WorldDefinition, Hero, repair_report }
        │ user reviews / edits / validates
        ▼
existing atomic ComposeWorldInput
        │
        ▼
World → WorldVersion → Run → RunState → Turn[]
```

- 草案是响应值，不存表、不带 draft ID，也不跨 Host 重启恢复；用户需要重新生成或保留自己的
  编辑文本。这避免建立第二个生命周期和“未确认世界”的删除问题。
- 生成请求必须引用已存在的 `model_profile_id`。模型输出仅允许世界名、摘要、主角名/出身、地点名、
  两位角色的身份描述与世界书文本；Python 负责映射章节/choices/Flag/关系 event/routes/endings
  的受限模板。模型候选的未知字段一律拒绝。
- `DraftValidationResult` 返回 `valid`、`definition`、`hero`、`repairs[]` 与
  `issues[{path,message}]`。`valid=false` 绝不返回可确认的 compose payload。
- 导出遵循既有 WorldVersion export API；确认后，原生角色卡由 V3 mapper 导出，世界书由
  World Info mapper 导出。

## 雾港等复杂度 vertical slice

示例 brief：`潮雾港口的悬疑恋爱冒险；温柔而危险；失踪航图引发潮门灾变；主角是流浪水手；
偏好两名可发展关系的角色。`

生成后的候选必须达到：

- `hybrid` ruleset，2+ locations，2 张角色卡，2 条关系定义，每条至少好感/信任两个维度；
- 3 个顺序章节和每章至少 2 个 choice；每一个 effect 均可由 Python 的现有 effect executor
  应用；
- 至少两条 route、至少 1 个 good、1 个 bad ending；ending 条件只使用现有的受限 predicate；
- 三次 choice 后，由 Python 锁定 ending；回滚后恢复到先前 revision，模型只叙述已验证 outcome。

## 验收与矩阵影响

| 矩阵维度 | 80 分所需新增证据 | 85 分所需新增证据 |
|---|---|---|
| Creation & content interoperability | 打包 Mac：真实本地模型生成 → 审阅编辑 → schema validate → compose；角色卡 V3 与 World Info 导出 round-trip；生成/取消/无效/重复确认测试 | 至少两种题材的重复旅程，真实卡 file chooser 与导出再导入无信息丢失 |
| Game loop & rule truth / state command safety | 生成草案三 choice、结局和回滚；证明模型响应不含可执行 command 且 Python 产生实际 effects | 真实模型降级/重试与回滚重放下，所有生成世界仍无越权状态写入 |
| Model & stream robustness | 真实配置模型的空/非 JSON/schema 无效响应均以非持久化错误恢复 | Huihui 14B 多次生成、取消/超时恢复与模型协议矩阵复验 |
| Desktop UX & accessibility | 打包 Tauri 中键盘完成创作、审阅、编辑、确认、游玩、回滚；屏幕阅读器标签检查 | 重复目标机旅程无 P0 发现 |

这是一项能力和证据计划，**不因代码或草案生成存在而直接加分**。只有上述真实模型和用户
旅程取证通过，才能调整相应分数；Android/host、长局和签名 RC 的现有门槛不变。

## 分阶段计划

1. **Draft boundary**：输入/输出模型、受限 JSON extractor、schema/语义校验、确定性 repairs、
   provider/空输出/非法候选测试。
2. **Mac review**：模型档案选择、brief 表单、草案预览和 JSON 编辑/验证/取消/重复确认恢复；
   原子 compose 无替代写路径。
3. **雾港复杂度验收**：mock 合同测试 + Huihui 14B 真实生成，完整三回合/结局/回滚及
   content export evidence。
4. **自由题材扩展**：只有在 vertical slice 可重复通过后，增加 prompt library 和题材预设；
   不放宽 schema/command 白名单。
