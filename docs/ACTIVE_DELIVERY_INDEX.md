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
- 桌面 v0.16.0 的玩法成熟度 88.1 可用于定义质量下限；vNext 的 Phase 0 初始评分为 0，不继承 legacy 分数。
- Android remote acceptance 78.1 证明已有功能方向，但 vNext 仍必须重新完成 Mac + Android + LAN 物理验收。
- **Phase 0 已验证：** 实现提交为 `401c7be`。Python 3.13.3 的独立 venv 中，`pytest -q` 为 `4 passed`、`ruff check src tests` 通过；临时 `DZMM_NEXT_DATA_DIR` 执行 `alembic upgrade head` 后，`schema_meta` 有 app/api/contract 三条基线记录、`alembic_version=0001_phase0`；`/health` 返回 `api_version=2`、四份契约、`storage=isolated` 与 `foreign_keys=true`。评分器读取 `vnext/eval/evidence/phase0.json` 得 **0.0/100**、所有 P0 未达标、不可发布——这是尚未实现功能的正确零基线，不得据此加分。
- **Phase 1 中间证据（已评分，未过 gate）：** `9bf5f4f` 在临时 SQLite 上验证了 World/WorldVersion/Hero/Run 的单事务 compose、重试、冲突与 20 次数据库写失败零残留；还覆盖三回合、SSE 事件与刷新恢复。`d413a87` 将模型 profile 固化为完整协议并验证 LM Studio 的 HTTP 200 error body 必须失败。`ca82df6` 把 Run 绑定到 profile，并以台式机 LM Studio 的 `huihui-ai_qwen3-14b-abliterated` 完成四回合实跑：Python 最终状态为地点/库存/revision 的唯一来源，Qwen RP 包装与 JSON 回显会被净化。桌面 vNext 的 `npm run build` 已通过，浏览器实测 Create → Confirm → Turn → Refresh 恢复成功。
- **当前 vNext 矩阵：37.5 / 100，全部 P0 未达标，不可发布。** 取证文件为 `vnext/eval/evidence/phase1-interim.json`：Domain 45、Game Loop 50、Content 35、Model 55、Desktop 50、Mobile 0、Long-play 0、Engineering 50。低分不是实现失败的代名词，而是如实反映缺少 archive/purge、Lore/ST、Tauri RC、Android、长局和发布证据；不以局部真实模型成功推断这些维度完成。

### 下一关

Phase 1 剩余：补齐模型取消/空流错误路径和 Tauri 打包桌面壳的验收；随后转入 Phase 2 的 archive/purge manifest、零孤儿扫描、rollback 与 30 回合真实模型跑团。不得从 legacy 目录复制领域模型或 API。
