# Active Delivery Index

## DZMM vNext 干净重做

- **状态：** Active — Phase 0 gate passed; Phase 1 is next
- **日期：** 2026-08-16
- **工作树 / 分支：** `.worktrees/dzmm-vnext` / `feature/dzmm-vnext`
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
- **Phase 0 已验证：** Python 3.13.3 的独立 venv 中，`pytest -q` 为 `4 passed`、`ruff check src tests` 通过；临时 `DZMM_NEXT_DATA_DIR` 执行 `alembic upgrade head` 后，`schema_meta` 有 app/api/contract 三条基线记录、`alembic_version=0001_phase0`；`/health` 返回 `api_version=2`、四份契约、`storage=isolated` 与 `foreign_keys=true`。评分器读取 `vnext/eval/evidence/phase0.json` 得 **0.0/100**、所有 P0 未达标、不可发布——这是尚未实现功能的正确零基线，不得据此加分。

### 下一关

Phase 1：实现 `World → WorldVersion → Run → Turn[]` 的原子 idempotent compose、首次 `RunState` 与三回合可恢复桌面竖切；以 20 次失败注入和刷新恢复结果争取总分至少 45、Domain 与 Game Loop 至少 40。不得从 legacy 目录复制领域模型或 API。
