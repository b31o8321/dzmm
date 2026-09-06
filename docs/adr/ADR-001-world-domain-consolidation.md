# ADR-001：收敛世界领域为单一所有权聚合

**状态：** Superseded by ADR-002
**日期：** 2026-08-16  
**决策人：** 产品负责人、DZMM 工程负责人

## Context

DZMM 当前存在 `World`、`WorldFramework`、`Screenplay` 三种重叠的世界/剧情容器。一个开放世界 session 同时引用 `world_id` 与 `framework_id`，但两者没有一对一关系；新向导用四个 HTTP 请求创建它们。删除逻辑按旧模型手工列出子表，遗漏 framework runtime state，且 SQLite 并未由应用统一启用 FK cascade。

这导致三类不可接受的状态：创建半成品、删除后的不可见孤儿、同一事实被剧本和 framework 双重控制。

## Decision

保留现有 `World` 作为**唯一用户可见的世界根**，并将 `WorldFramework` 变为其唯一可选的结构化模板组件：

```text
World (canonical root)
├── LoreEntry[]                  narrative knowledge; never mutates state
├── Character[]                  reusable PCs
├── Framework? (1:1)             locations/factions/NPC templates/events/campaign
├── LegacyScreenplay[]           read-only compatibility until migrated/retired
└── Session[]                    play runs
    └── RuntimeState[]           only session-owned mutable state
```

实现上，新增 `WorldFramework.world_id`（unique FK），回填现有 `Session(world_id, framework_id)` 对。新建开放世界使用一个 `POST /worlds/compose` 命令，在单个数据库事务中写入 World、Framework、PC、Session 及 runtime 初始状态。LLM 生成永远只产生可编辑草稿，最终提交才写数据库。

删除、归档、导入、导出集中到 `WorldLifecycleService`；路由不得各自维护子表名单。数据库连接统一开启 SQLite FK；迁移为需要重建表的 schema 使用受版本控制的 Alembic/SQLite rebuild 迁移，而不是继续只追加列。

## Options considered

### A. 全量重写数据模型与前端

| 维度 | 评估 |
|---|---|
| 复杂度 | 极高 |
| 用户存档风险 | 极高 |
| 短期收益 | 中 |
| 长期清晰度 | 高 |

优点：命名和表结构最干净。  
缺点：会丢失 v0.16 的长局、恢复、模型兼容回归保护；Android 分支需要重做；无法安全迁移真实本地存档。

**结论：拒绝。**

### B. 保持双根，只补删除 if/else

| 维度 | 评估 |
|---|---|
| 复杂度 | 低 |
| 用户存档风险 | 中 |
| 短期收益 | 低 |
| 长期清晰度 | 低 |

优点：可以很快减少一个缺陷。  
缺点：不能阻止四次提交的孤儿资源，也不会解决“世界到底是什么”的产品认知。

**结论：拒绝，最多作为进入迁移前的止血补丁。**

### C. 兼容迁移到单一 World root（采用）

| 维度 | 评估 |
|---|---|
| 复杂度 | 高但可分阶段 |
| 用户存档风险 | 可控，需要备份与校验 |
| 短期收益 | 高 |
| 长期清晰度 | 高 |

优点：保留 `world_id` 这一广泛使用的稳定外键，逐步收编 Framework、Lore 与旧剧本；可让新旧 session 并存到迁移完成。  
缺点：迁移期间会有适配层，不能一次删除旧 API。

**结论：采用。**

## Consequences

- 新功能只可依赖 `WorldLifecycleService` 和 canonical World manifest；禁止增加第二个世界根。
- `Screenplay` 成为 legacy compatibility 或显式的 adventure template，不再与 Framework 共同控制开放世界回合。
- 删除世界默认归档；物理清除只能从 World Center 发起，并显示 framework、session state、assets、RAG index 和外部导入 escrow 的完整影响。
- 现有世界可继续游玩；迁移失败必须保持旧数据只读可恢复，绝不自动删除。
- Android remote API 保持 gameplay-only。其会话读取接口可以增加 `world_manifest_version`，但不能在真机验收前破坏当前契约。

## Action items

1. [ ] 为创建失败、session/world 删除、框架回填建立临时 DB 回归测试。
2. [ ] 实现 `WorldLifecycleService` 和统一 manifest/impact preview，不改变默认 UI。
3. [ ] 加入 schema migration、备份和完整性报告；回填 `WorldFramework.world_id`。
4. [ ] 将开放世界向导切换到原子 compose endpoint；冻结旧向导的写入入口。
5. [ ] 引入 LoreEntry 和 SillyTavern V3 / World Info import preview。
6. [ ] 将 World Center 作为唯一管理入口，旧 Worlds/Screenplays 页面转为兼容视图后再下线。
