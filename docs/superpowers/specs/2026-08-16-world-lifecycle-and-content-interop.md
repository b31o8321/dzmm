# DZMM 世界生命周期与内容互通规格

## Problem statement

玩家创建开放世界时，实际会写入多套互不绑定的资源；失败、重试或删除后无法确信世界是否完整、是否仍有隐性数据。与此同时，酒馆生态中可复用的角色卡和条目式世界书无法自然进入 DZMM，用户必须从零输入设定。

本规格以一次领域收敛解决这两个问题：世界成为唯一所有权根；外部内容作为可审阅、可提升的知识输入；已验证的开放世界回合内核不重写。

## Goals

1. 任意“创建世界并开局”在成功时完整创建，在失败/重试时不留下任何不可见资源。
2. 世界删除或归档可以准确预览并覆盖全部子资源；完整性检查结果为零孤儿。
3. 导入 SillyTavern V3 角色卡与 World Info 后，用户能在 3 分钟内将其用于新世界，不丢失未知字段。
4. Framework 的地点、NPC、势力、事件继续是运行时唯一结构事实源；Lore 不得直接改变状态。
5. 保留所有既有存档的可玩性，且 v0.16 的 50 回合与恢复回归不下降。

## Non-goals

- 不复刻 SillyTavern 的完整 Prompt Manager、Regex Script、插件脚本或所有 provider 参数。
- 不在本计划内实现多人桌、群聊 Bot、公共云同步或 iOS。
- 不自动把 Lore 条目转成地点/NPC/事件；必须有用户确认。
- 不在 Android remote RC 真机验收前重写远程 gameplay API。

## User stories

- 作为新玩家，我要在一个页面生成、检查并确认世界、角色和开局，以便失败时不会留下难以理解的半成品。
- 作为长期玩家，我要先归档世界，再在明确看到将删除哪些存档/资源时选择永久删除。
- 作为酒馆内容拥有者，我要导入角色卡和世界书，并看到哪些字段被使用、保留或忽略。
- 作为世界作者，我要把一条 lore 明确提升为“地点”或“事件”，以便它开始参与规则与状态推进。
- 作为旧存档玩家，我要无需迁移操作即可继续原来的跑团。

## Requirements

### P0 — 生命周期安全与领域收敛

1. **Canonical manifest**
   - `World` 是唯一用户可见根；`WorldFramework.world_id` 是唯一 FK。
   - 一个 World 最多一个 Framework；每个新 Framework 必须绑定一个 World。
   - `GET /worlds/{id}/manifest` 返回 World、Framework、角色、存档、legacy screenplay、assets、lore、RAG index 的计数与版本。

2. **Atomic compose**
   - `POST /worlds/compose` 接收经用户确认的 draft，在一个数据库事务中创建 World、Framework、Character、Session 和初始 runtime state。
   - 任一约束、写入或请求失败后 rollback；同一 `request_id` 重试最多产生一个完整世界。
   - 向导生成步骤只保存在本地草稿或明确的 server draft，不直接提交领域资源。

3. **Unified lifecycle**
   - `WorldLifecycleService.preview_delete()` 返回精确资源清单；`archive()` 与 `purge()` 是唯一删除入口。
   - purge 删除 framework child、所有 session runtime state、legacy child、RAG/NPC memory/asset 引用；每个外部文件清理记录结果。
   - SQLite connection 启用 FK；应用层仍按领域顺序清理非 SQL 资源。
   - `DELETE /sessions/{id}` 必须删除五张 `Session*State` 表；删除 world 必须覆盖 Framework。

4. **旧数据迁移与恢复**
   - 启动迁移前生成带 manifest 的本地备份；可从备份恢复。
   - 对每个 `Session.framework_id` 回填唯一 `WorldFramework.world_id`；歧义记录为阻塞项，不猜测。
   - migration 后运行 referential-integrity report：所有 FK、session runtime state、RAG/asset references 无孤儿。

### P1 — Lorebook 与角色卡互通

1. `LoreEntry` 字段：title、body、activation、keywords、priority、anchor、source_format、source_payload、created_at/updated_at。
2. 导入 ST V3 character card、PNG metadata 与 World Info JSON；显示 supported / preserved / ignored 字段报告。
3. `source_payload` 保存外部未知字段，导出时可无损带回；禁用外部 regex/script/概率执行。
4. prompt context 采用确定性预算：Framework facts 优先，Lore 按 always → keyword → optional semantic recall 排序；记录本回合入选条目 ID。
5. Lore 提升为结构实体时产生显式 diff 与用户确认；提升后建立一个 source link，避免重复编辑漂移。

### P1 — 世界中心体验

1. World Center 显示“草稿 / 可游玩 / 已归档”三态，不让用户面对 World 与 Framework 两个概念。
2. 删除默认操作是“归档”；永久删除必须经过 manifest 预览和键入世界名确认。
3. Session 页只能删除单个 run；删除世界的入口跳转 World Center，不提供模糊的三级 nuking。
4. 玩家视图显示当前地点、事件、关系和可追踪目标，但不泄漏 hidden state。

### P2 — 后续观察

- ComfyUI/本地生图的可选场景资产；失败不影响回合提交。
- 多人桌、主持人权限和聊天平台 bridge。
- 更多内容 adapter（Risu、CharX、Hoplight package）。

## Delivery plan

| Phase | 产出 | 依赖 | 验收门槛 |
|---|---|---|---|
| 0. Freeze & audit | domain inventory、真实 DB 只读扫描工具、失败矩阵 | 不碰真实存档 | 临时 DB 能重现四步创建中断与现有孤儿。 |
| 1. Data-safety hotfix | 补 session framework runtime 删除、world framework 影响预览、删除回归测试 | Phase 0 | 每个删除入口后 SQL 与文件完整性报告为零孤儿。 |
| 2. Canonical root | `WorldFramework.world_id`、manifest、迁移/备份、lifecycle service | Phase 1 | 新旧 DB upgrade、回滚、50 回合恢复均通过。 |
| 3. Atomic creation | compose endpoint、新向导切换、旧写入入口 deprecate | Phase 2 | 故障注入 20 次、每次为 0 或 1 个完整聚合。 |
| 4. Content interoperability | LoreEntry、ST V3/World Info preview/import/export | Phase 2 | 10 个混合条目的映射报告可重复，未知字段可 round-trip。 |
| 5. World Center | 新管理入口、归档/永久删除 UX、状态面板提升 | Phase 2-4 | 用户旅程：创建、失败恢复、归档、恢复、永久删除、刷新后状态正确。 |
| 6. Legacy retirement | 标记/迁移旧 screenplay path、移除死入口 | Phase 3 & 5 | 无 production caller 使用 legacy write API；兼容读取有到期版本。 |

Android remote acceptance 是并行但独立的发布流：先完成真机、路由器、30 回合和 100 回合断线验收；领域重整 branch 之后再从最新 main 适配，避免在同一个 PR 中同时改变网络与持久化风险。

## Success metrics

- 创建失败或重试导致的 orphan aggregate：0。
- World purge 后 referential-integrity report 的 dangling SQL/file reference：0。
- World Info import：>=90% 支持字段可解释映射，100% 未支持字段留在 escrow。
- 新建到第一回合的中位时间：比当前双路径基线降低 >=30%。
- 迁移后 v0.16 长局回归：50/50 回合、状态恢复、模型协议与删除测试全部通过。

## Open questions

- **产品：** 归档保留期是默认 30 天，还是仅支持本地手动永久删除？
- **产品：** 旧“手动世界 + 剧本”是否保留为高级模式，还是在 vNext 只保留导入？
- **工程：** 真实用户库中是否存在一个 Framework 被多个 World 语义复用的异常数据？必须由只读扫描回答。
- **设计：** Lore 触发第一期是否只做关键词，还是同一版本接现有 RAG？建议先关键词，保证可解释性和 token 可控。
