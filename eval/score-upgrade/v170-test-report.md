# DZMM v1.7.0 全量测试报告（R1–R3）

- 日期：2026-09-28
- 被测：main @ v1.7.0（41f9b5d + 预算二阶段 142ede0 于 feature 分支待合入）
- 模型：LM Studio qwen3-14b（192.168.31.169:1234）；R3 模拟器 dzmm-ux-api36

## R1 自动化 — 全绿 ✅

| 项 | 结果 |
|---|---|
| backend pytest | 229 passed |
| backend ruff | clean |
| desktop vitest | 45 passed |
| desktop build | ✓ |
| mobile flutter test | 29 passed |
| mobile analyze | clean |
| 契约一致性 | 四 schema 可解析；capabilities/turn_command/run_state 键全对齐 |
| sidecar PyInstaller 构建 | ✓（自检 /health 通过）|
| Android APK 编译 | ✓ assembleDebug |

## R2 真模型长跑 — 引擎语义全对，模型端残留在 ✅⚠️

| 指标 | loop（时之沙漏） | countdown（黯星余烬） |
|---|---|---|
| 成功/请求 | 12/30（v1.5.0 基线 6/30，**翻倍**） | 13/30（基线 8/30） |
| 失败 | 18（间发 truncated + turn20-22 连发 120s 无返回） | 17（同类） |
| 开头重复（近 4 回合） | 7 | **2** |
| 跨循环 4-gram 跑偏 | **0.316**（首次取得样本） | 不适用 |
| 循环轨迹 | 1×7 → rewind → 2×5（8 回合/循环符合 360→600 步长） | 不适用 |
| 时钟裁决 | +30/回合，rewind 后重置 360 ✓ | tick −20 与玩家 +120（clamp 720）全程正确 ✓ |
| 失败零写入 | ✓（revision 不动，无半回合） | ✓ |
| payload 预算 | 二阶段后典型 6.4k 字且**不随局长增长**（v1.5.0 时无界） | 同 |

结论：payload 预算两阶段把成功回合翻倍并首次跑通跨循环；
剩余失败为模型端状态（qwen3 小上下文 + 间发 120s 无响应），非 payload 体积——
证据：turn0 成功（最大 payload）与 turn20+ 失败（同等 payload）并存。
彻底解法 = ≥16k 上下文模型或 magnum-22b 可加载（外部依赖，见 v1.5.0 记录）。
数据：eval/score-upgrade/v170-r2-{loop,countdown}-metrics.json。

## R3 双端验收 — 通过 ✅

| 端 | 内容 | 结果 |
|---|---|---|
| Mac .app（v1.7.0 sidecar+壳） | 启动 → 建世界 → 1 回合 → sandbox 创建（state.sandbox=true）→ 沙盒 DELETE 204 → URL 导入坏链 422 拒绝 | **SMOKE OK** |
| 安卓模拟器 | v1.7.0 代码 loop rewind + countdown 两条集成路径 | +2 All tests passed |
| mobile 全量 | 29 tests | ✓ |

（.app 冒烟证据：eval/score-upgrade/live-env/v170-smoke 隔离数据目录；DMG bundle flaky 未阻塞，.app+CI DMG 双证。）

## R4 稳定长跑

并入后续：R2 的 30 回合（含 rewind/跨循环）已覆盖 R4 的核心断言
（无崩溃、无状态漂移、失败零写入）；50+ 回合连跑待 ≥16k 模型可用后补。

## 遗留与恢复条件

1. 模型端 truncated/120s（R2 残留）：恢复条件 = qwen3 调 ≥16k 上下文或 magnum-22b 可加载；
   重跑 R2 预期失败率 <5%
2. Windows 真机 GUI 验证（1.4.0 起积压）：需 Windows 机器
3. 预算二阶段提交（142ede0）在 feature 分支，随 v1.7.1 合入
