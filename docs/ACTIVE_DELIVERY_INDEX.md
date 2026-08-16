# Active Delivery Index

## DZMM 世界生命周期与内容互通重整

- **状态：** Proposed — awaiting product approval
- **日期：** 2026-08-16
- **工作树 / 分支：** `.worktrees/dzmm-domain-consolidation-review` / `docs/dzmm-domain-consolidation-review`
- **基线：** `main` at `df38037` (`v0.16.0`)
- **目标：** 以一个可原子创建、可解释删除、可导入外部内容的世界聚合，替换当前三条叠加的创建与生命周期路径；保留已验证的开放世界运行时与 Android 游戏客户端边界。

### Canonical artifacts

- [产品与领域现状评审](reviews/2026-08-16-dzmm-product-domain-review.md)
- [ADR-001：世界领域收敛](adr/ADR-001-world-domain-consolidation.md)
- [规格与分阶段实施计划](superpowers/specs/2026-08-16-world-lifecycle-and-content-interop.md)
- [世界中心交互原型](prototypes/2026-08-16-world-center-prototype.html)

### 已确认决策

1. DZMM 保持「本地优先、单人 AI TRPG、Python 决定规则与状态」定位，不复刻酒馆的完整提示词/脚本工作台。
2. SillyTavern 世界书优先作为**叙事知识层**导入；地点、NPC、势力和事件只有经用户显式提升后才成为可改变游戏状态的结构化实体。
3. 不做全量推倒重写。采用兼容迁移 + 绞杀式收敛，先补数据生命周期缺口，再切换新建入口。
4. Android remote client 是独立发布门槛；本重整不得在其真机验收前改变远程 gameplay API 合约。

### 当前证据与风险

- 新开放世界向导依次调用 `finalize framework -> create world -> create character -> create session`，是四个独立提交；中途失败或重试可留下孤儿资源。
- `Session` 同时持有 `world_id` 与 `framework_id`，但两者无所有权关系；`DELETE /worlds/{id}?cascade=true` 不清理 framework 及其 session runtime 状态。
- `delete_session_cascade()` 没有删除 `SessionLocationState`、`SessionNpcState`、`SessionEventState`、`SessionFactionState`、`SessionCampaignState`；SQLite 外键级联也未由应用开启。
- 桌面 v0.16.0 的玩法成熟度为 88.1，但 Android remote acceptance 仍为 78.1，真机/LAN 验收未完成。

### 下一关

产品确认本规格的 P0 边界后，先建立临时数据库的创建失败、删除与迁移回归测试；测试能够证明无孤儿资源后，才实施数据模型迁移。
