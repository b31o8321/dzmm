# Active Delivery Index

## DZMM vNext 干净重做

- **状态：** Active — Phase 0–3 的已实现范围已有中间证据；当前进入打包桌面壳、模型流失败恢复与长局验收，随后才进入 Android/LAN RC
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
- **Phase 2 lifecycle 证据（已评分，未过 gate）：** `cde8ef3` 实现了 archive、确认 token 保护的 purge manifest、聚合删除与零 SQL 孤儿扫描；测试还确认 archived World 不能再收回合。当前没有资产或派生索引模块，manifest 因此明确报告空集合，不把不存在的清理能力计为完成。
- **Phase 2 rollback 证据（已评分，未过 gate）：** `abf1f60` 将回滚实现为新的审计 Turn，`edf4ac1` 将它接入桌面。浏览器在临时 DB 中验证两回合 → 恢复第一回合后 → 刷新：历史仍有三条记录，RunState 为新 revision 的第一回合快照。此测试使用 deterministic narrator；真实 Huihui 模型只为此前四回合证据背书，不能替代长局。
- **Phase 3 content 证据（已评分，未过 gate）：** `53250f8` 支持 SillyTavern V3 card 与 World Info 解析、原始条目保留、关键词/常驻/优先级/预算选择，并让 Lore 提升产生 WorldVersion 2、既有 Run 留在版本 1。模型仅接收选择出的 Lore body，不能把 Lore 直接写入 RunState。
- **Phase 3 desktop import 证据（已评分，未过 gate）：** `602a568` 的临时 DB 浏览器 E2E 验证 V3 卡 → 1 条 Lore → 建议 Hero → 单一 compose → 确认页面；Lore 没有静默变成实体。
- **Mac Host 打包中间证据（已评分，未过 gate）：** `b53da75` 以 PyInstaller 生成 arm64 sidecar，首次启动完成 Alembic 至 `0005_turn_rollbacks` 并返回 vNext `/health`；它被放入 Tauri debug `.app`，以独立端口和临时 `DZMM_NEXT_DATA_DIR` 启动该 `.app` 后，WebView 触发 Host command 并启动同一个 sidecar。该证据只证明打包和启动边界；尚未在打包应用中完成 create/play/archive/recovery 与无障碍旅程，不能加分。
- **真实模型流与长局中间证据（已评分，未过 gate）：** `078c268` 让 SSE token 在回合提交前传输，畸形/空流、429 与客户端取消都不会写入半回合。`phase2-real-model-30-turns.json` 记录台式机 Huihui 14B 在临时数据库的 30 回合实跑（中位 0.519 秒，最大 3.053 秒），最终 revision 与 Turn 数均为 30；未以此替代 50 回合、500 消息或实际设备指标。
- **50 回合与重开中间证据（已评分，未过 gate）：** `8409b01` 记录 50 回合 Huihui 14B 流式实跑（中位 0.553 秒，最大 3.045 秒、零重试）和 500 条持久化回合的确定性 API 重开（0.004 秒、165 KB）。这证明本地恢复，不替代目标设备的流式预算。
- **当前 vNext 矩阵：58.0 / 100，全部 P0 未达标，不可发布。** 取证文件为 `vnext/eval/evidence/phase4-performance-interim.json`：Domain 60、Game Loop 75、Content 60、Model 65、Desktop 60、Mobile 0、Long-play 75、Engineering 50。低分不是实现失败的代名词，而是如实反映缺少 PNG/导出 round-trip、Tauri RC、Android、目标设备性能和发布证据；不以局部真实模型成功推断这些维度完成。

### 下一关

补齐打包桌面的 create/play/archive/recovery 与无障碍验收；执行 50 回合/500 消息性能验收，随后推进 Android/LAN RC。达到每项证据的实际门槛前，不得从 legacy 目录复制领域模型或 API。
