# Active Delivery Index

## DZMM vNext 干净重做

- **状态：** Active — clean-slate scope confirmed
- **日期：** 2026-08-16
- **工作树 / 分支：** `.worktrees/dzmm-domain-consolidation-review` / `docs/dzmm-domain-consolidation-review`
- **基线：** `main` at `df38037` (`v0.16.0`)
- **目标：** 在隔离的 vNext 产品根中重建 DZMM：单一版本化世界聚合、可恢复 Python-first 回合、受限 Lorebook/内容导入、Mac host 与 Android gameplay client。旧数据库、旧 API 和旧代码不构成迁移或兼容约束。

### Canonical artifacts

- [产品与领域现状评审](reviews/2026-08-16-dzmm-product-domain-review.md)（历史与设计参考）
- [ADR-002：vNext 干净重做](adr/ADR-002-vnext-clean-slate-rebuild.md)
- [vNext 规格、评分矩阵与分阶段实施计划](superpowers/specs/2026-08-16-dzmm-vnext-clean-rebuild.md)
- [世界中心交互原型](prototypes/2026-08-16-world-center-prototype.html)

### 已确认决策

1. DZMM 保持「本地优先、单人 AI TRPG、Python 决定规则与状态」定位，不复刻酒馆的完整提示词/脚本工作台。
2. vNext 不迁移真实用户数据，不兼容旧 API、旧 schema 或旧页面；`main` 只作为产品行为和测试设计的参考。
3. 世界是一个版本化 aggregate；WorldBook 是受限叙事知识层，不能直接写入运行态。
4. Android 仍为 gameplay-only client，Mac 为 host；vNext 使用版本化的独立 API，而不是兼容旧远程接口。
5. 每阶段只能按 vNext 成熟度矩阵累积证据；旧项目的 88.1 成熟度和 Android CI 不能转移为 vNext 分数。

### 当前证据与风险

- v0.16 的重叠领域模型与手工级联删除是 vNext clean-slate 的触发证据，而不是待迁移负担。
- 桌面 v0.16.0 的玩法成熟度 88.1 可用于定义质量下限；vNext 首次评分为 0。
- Android remote acceptance 78.1 证明已有功能方向，但 vNext 仍必须重新完成 Mac + Android + LAN 物理验收。

### 下一关

在 `.worktrees/dzmm-vnext` 创建干净产品根与新数据库后，先完成 Phase 0 的可运行骨架和评分 harness；不得从 legacy 目录复制领域模型或 API。
