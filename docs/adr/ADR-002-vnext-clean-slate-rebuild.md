# ADR-002：采用 vNext 隔离产品根的干净重做

**状态：** Accepted  
**日期：** 2026-08-16  
**决策人：** DZMM 产品负责人

## Context

用户明确不要求保留当前数据、旧 API 或旧实现兼容。当前项目经历 screenplay-first、framework、Python 规则引擎与 Android remote 等多轮叠加；继续在原结构上做兼容迁移会把历史表、双重语义和手工删除规则带入下一阶段。

v0.16 的核心玩法、模型协议与 Android 方案有可复用的产品经验，但不应成为 vNext 的代码依赖或成熟度得分。

## Decision

在同一仓库的新 vNext 产品根中从零实现，而非修改 legacy `backend/`、`frontend/`、`mobile/`：

```text
vnext/
├── backend/        FastAPI + fresh SQLite schema + Alembic
├── desktop/        Tauri + Vue world-management shell
├── mobile/         Flutter Android gameplay-only client
├── contracts/      API/OpenAPI, event schema, world/run JSON schema
├── eval/           deterministic fixtures, model replay and score harness
└── packaging/      vNext-only build/release artifacts
```

vNext 的 core model 只有三个持续对象：

```text
World ──> WorldVersion ──> Run ──> Turn[]
                 │              └── RunState (versioned JSON)
                 └── WorldDefinition (validated JSON: lore, graph, NPC, events, rules)
```

- `WorldVersion` 是不可变的已发布世界定义；编辑世界会生成新 version，已经开始的 Run 永远指向自己的 version。
- `RunState` 是唯一的可变游戏状态，Python engine 接收已验证 command 后更新它；LLM 永不直写数据库。
- `Turn` 同时记录 request id、玩家输入、叙事、command、state revision 与诊断，成为回滚与恢复的唯一审计单位。
- Lorebook 是 WorldDefinition 的受限条目集，按明确 activation 选择上下文；只有用户显式“提升”为实体才改变结构世界。
- macOS/Windows 桌面 Host 与 Android 走新的 `api_version=2` capability contract；Android 不管理模型、世界、密钥或删除操作。

## Options considered

### A. 在 legacy 主线继续兼容迁移

| 维度 | 评估 |
|---|---|
| 交付速度 | 中 |
| 领域清晰度 | 低 |
| 历史负担 | 极高 |
| 数据风险 | 中 |

优点：可以重用更多代码。  
缺点：需要维护三种创建/删除语义，无法真正移除老 schema 和 route。

**结论：拒绝。**

### B. 同仓库隔离 vNext 根（采用）

| 维度 | 评估 |
|---|---|
| 交付速度 | 中 |
| 领域清晰度 | 高 |
| 历史负担 | 低 |
| 数据风险 | 低 |

优点：保留 GitHub、打包和学习资产；新编译/数据目录天然隔离；能逐项拿回成熟度证据。  
缺点：短期会存在两个产品根，必须防止直接复制 legacy 领域代码。

**结论：采用。**

### C. 新建独立仓库

| 维度 | 评估 |
|---|---|
| 交付速度 | 低 |
| 领域清晰度 | 高 |
| 运维摩擦 | 高 |
| 可追溯性 | 低 |

优点：物理隔离最彻底。  
缺点：分散 issue、release、artifact 和上下文；当前不带来额外用户价值。

**结论：暂不采用。**

## Consequences

- vNext 不读取 `~/.dzmm/dzmm.db`；开发与 RC 使用独立 `~/.dzmm-vnext/` 目录和新的 application identifier。
- 不做旧存档导入、旧 URL/API 兼容、旧模型配置迁移或旧世界迁移；用户需要手工导入内容包或新建。
- 所有 schema 均由 Alembic 管理，SQLite foreign keys 在每个连接上显式开启；不再使用“仅加列”的迁移机制。
- 新代码从最小 vertical slice 开始。可以借鉴 legacy 的测试场景、协议错误边界和 UI 文案，但不得引用其 ORM、route 或 service 模块。
- promotion 到主产品前，需要在新的成熟度矩阵获得全部证据；不以 legacy 测试绿灯代替。

## Action items

1. [ ] 创建 `feature/dzmm-vnext` 和 `.worktrees/dzmm-vnext`，初始化 vNext 产品根与独立 app data path。
2. [ ] 锁定 contracts：WorldDefinition、RunState、TurnCommand、SSE event、API capability。
3. [ ] 建立评分 harness 与 Phase 0 baseline，任何功能没有证据不得加分。
4. [ ] 按 vNext spec 的 phase/gate 推进；每个 gate 更新 Active Delivery Index。
