# DZMM replacement-candidate Active Delivery Index

更新时间：2026-09-03
工作树：`.worktrees/dzmm-vnext`
分支：`feature/dzmm-vnext`
基线：`main` at `df38037`

## 当前目标

DZMM vNext 是“本地优先、状态驱动的互动叙事平台”。macOS、Windows、Android
都是独立 Local Host：本机 SQLite、共享 Python 状态裁判和完整 ModelProfile。跨设备只允许
用户明确执行的 portable export/import/clone，不做自动同步或同一 Run 双端写入。

自 2026-08-21 起，发布判断以安装后的玩家旅程为第一事实源：玩家必须能快速设置模型、从可复用
World 继续或新建 Run、先看到有角色和引导的开场、理解 LLM 当前阶段、沉浸完成回合和正式结局，
并从同一 World 开始下一局。API、构建、模拟器自动点击和长回合脚本只证明工程能力，不能替代可玩性。

完成门槛：所有 P0 维度及整体成熟度均 >=85；正式代码、UI、测试、配置、依赖、迁移和发布产物中不再存在废弃的 remote/LAN/mDNS/QR/pairing/scope 能力。统一命名和旧版删除遵循 [ADR-010：单一 DZMM 受控替换](adr/ADR-010-single-dzmm-cutover.md)，在发布 gate 通过前不可执行不可逆删除。

## Canonical artifacts

- [ADR-008：每个平台都是 Local Host](adr/ADR-008-local-host-on-every-platform.md)
- [ADR-009：共享跨端体验契约](adr/ADR-009-cross-platform-adaptive-experience.md)
- [全平台 Local Host 规格、矩阵与 Plan](superpowers/specs/2026-08-19-local-host-all-platforms.md)
- [叙事规则集规格](superpowers/specs/2026-08-17-narrative-rulesets-interactive-story-platform.md)
- [AI 世界创作向导规格](superpowers/specs/2026-08-17-ai-world-creation-wizard.md)
- [共享 Experience Contract](../vnext/contracts/experience_contract.json)
- [共享 Design Tokens](../vnext/contracts/design_tokens.json)
- [玩家视角重定基线](reviews/2026-08-21-player-first-vnext-rebaseline.md)
- [三端玩家能力与代码质量评分](reviews/2026-08-21-cross-platform-player-code-scorecard.md)
- [玩家旅程验收清单](acceptance/2026-08-21-player-journey-acceptance.md)
- [玩家闭环交互原型](prototypes/2026-08-21-player-loop.html)

历史 ADR、规格、截图和 evidence 不再作为当前能力证明；仍保留的历史快照已标记
`historical-superseded`，不得计入当前矩阵。

## 2026-08-21 玩家可玩性重定基线与实现进度

真实 Android 体验和老版 `main` 对照证明，vNext 当前是“框架可运行、主循环未完成”：

- Android 世界列表点击没有动作，desktop 世界详情也没有继续/新 Run 主动作；core 不提供从已有
  World 创建 Run 的 use case。
- compose 会直接创建 World、Version、Hero、Run；初始 Run 没有 opening story beat，玩家先看到 choices。
- Android 回合是阻塞 MethodChannel，游玩页只禁用按钮；desktop 也没有使用已存在的流式 endpoint。
- narrative ruleset 展示自由行动输入，却拒绝非 choice 状态变化。
- ending 只有锁定状态和内部类型，没有正式结局叙事、回到世界或同世界新 Run。
- model profile 只有 create/list/probe，没有 edit/delete/default。

这份重定基线记录的是改动前的 **30/100**，不是当前实现评分。当前工作树已补齐上述主循环的
第一版实现，真实桌面浏览器 + 隔离后端已验证开场、慢模型阶段、取消零写入、回合叙事/状态反馈、
正式结局和同一 World 新 Run；Android 已通过自动化测试和 APK 构建，但尚未在物理设备验收。
当前暂定玩家评分 **78/100**，仍然发布阻断：Windows 安装包和 Android 真机证据缺失，macOS 当前
安装包虽然已完成 Host 级 30 回合重启恢复，但完整 WebView/可访问性和三端 30 回合验收尚未完成。
phase77 的安装包 Host 恢复证据，以及 phase78 的跨端 operation stage 契约/构建证据，分别见
`vnext/eval/evidence/phase77-macos-packaged-trpg-restart-recovery.json` 和
`vnext/eval/evidence/phase78-operation-stage-contract-parity.json`。

本轮建立的交互原型已通过浏览器实点：desktop 与 390×844 无横向溢出；World 继续/新 Run、开场
叙事、角色对话、选择/自由行动、`preparing/connecting/generating/applying`、慢模型、provider error、
取消恢复、模型编辑和结局后新 Run 均可演示。原型是验收面，不是正式功能证据。

## 已完成（可复核）

### 后端 Local Host 边界

- 删除 pairing、discovery/mDNS、host identity、confirmation ticket、remote/mobile 路由。
- 删除 LAN 配置、`zeroconf` 依赖、pairing/remote 迁移和专用测试。
- FastAPI 仅保留本机 `/api/v2/*` adapter；健康检查明确返回 `storage=local`、`host=127.0.0.1`。
- `dzmm_vnext.core.command_engine.apply_commands` 已成为 TurnCommand 的共享应用入口；FastAPI
  只注入 schema validator 和错误类型，后续 Android runtime 将直接复用该 core。
- 生命周期审计保留为本机能力，不再绑定设备身份。

证据：`cd vnext/backend && .venv/bin/python -m pytest -q`（112 passed，包括 30 回合本机回读、协议 200/error recovery、Experience Contract stage parity、Android 模型后台线程边界、共享叙事清洗/截断防线、可执行模型超时/连接恢复提示、Android World 归档/恢复 parity、回滚记录语义和系统安全存储凭据边界、AI 草案取消后零写入、release package extra gate、桌面离线/键盘边界、sidecar 父进程退出监控、retired route-surface guard、choice stream 和干净打包迁移边界）、Ruff 通过。

### macOS / Windows 桌面

- Tauri 只启动 `127.0.0.1` sidecar，无启动方式、LAN 开关、手机联动或配对页面。
- Vue 设置页改为本机服务、模型和外观；API 类型中删除 remote/pairing 类型与函数。

证据：`cd vnext/desktop && npm run build`、`src-tauri/cargo check` 通过；使用
`vnext/backend/.venv/bin/python vnext/packaging/build_backend.py` 生成 macOS arm64 sidecar 成功。
发布工作流已切换到 vNext 路径，并包含 macOS DMG 与 Windows NSIS 的 sidecar/runtime 内容检查；
该 CI 配置尚未替代实际 Windows 打包运行证据。

### Android Local Host UI 边界

- Flutter 从远程客户端重写为正式多入口 Local Host 壳：世界、创作、游玩、模型、设置。
- 删除发现、扫码、配对、Host URL/token 会话和远程 API 客户端；新增 `LocalHostPort` 与
  `EmbeddedPythonLocalHostPort` MethodChannel adapter。
- 删除网络发现/相机/权限依赖；主题和本机 Run/Model preference 使用 secure storage。
- Android 游玩和 AI 世界创作共用 `OperationStatusCard`，显示准备/连接模型/生成叙事/状态写入、耗时和慢模型说明；只有在状态写入前才允许取消。
- Chaquopy 17.0 已接入 Android debug 构建；bridge 可启动 Python 3.11，并通过
  `dzmm_vnext.core_runtime.LocalCoreRuntime` 使用 app-private SQLite、模型档案、compose、choice、
  ending、rollback 和 portable 操作。API 36 模拟器已完成三 choice、ending、rollback、force-stop/reopen
 和 SQLite 回读；phase59 已在同一模拟器取 direct Ollama Probe 成功，phase60 又完成 30 回合行动和重启回读。
phase68 又在不使用 adb reverse/TCP proxy 的情况下直连 PC LM Studio qwen3，完成草案到 rollback 的完整 Run。

证据：`flutter analyze`、`flutter test`、`flutter build apk --debug`、
`vnext/eval/evidence/phase56-android-embedded-python-spike.json`、
`vnext/eval/evidence/phase57-shared-core-android-build-smoke.json`、
`vnext/eval/evidence/phase58-android-local-host-vertical-slice.json`、
`vnext/eval/evidence/phase59-android-direct-model-probe.json`、
`vnext/eval/evidence/phase60-android-30-turn-local-ui.json`、
`vnext/eval/evidence/phase61-android-portable-roundtrip.json`、
`vnext/eval/evidence/phase62-android-ai-draft-direct-invalid-recovery.json`、
`vnext/eval/evidence/phase63-android-ai-draft-cancel-ux.json`、
`vnext/eval/evidence/phase64-experience-contract-parity.json`、
  `vnext/eval/evidence/phase65-pc-qwen3-json-schema-gate.json`、
`vnext/eval/evidence/phase66-pc-qwen3-full-journey.json`、
`vnext/eval/evidence/phase67-android-pc-qwen3-ui-full-journey.json`、
`vnext/eval/evidence/phase68-android-pc-qwen3-direct-lan.json`、
`vnext/eval/evidence/phase69-model-protocol-200-error.json`、
`vnext/eval/evidence/phase70-portable-cross-platform.json`、
`vnext/eval/evidence/phase78-operation-stage-contract-parity.json`、
`vnext/eval/evidence/phase79-android-operation-status-and-cancel.json`、
`vnext/eval/evidence/phase80-formal-ending-narrative-parity.json`、
`vnext/eval/evidence/phase81-model-profile-field-validation.json`、
`vnext/eval/evidence/phase82-android-background-model-operations.json`、
`vnext/eval/evidence/phase83-macos-vite-player-journey.json`、
`vnext/eval/evidence/phase84-clean-package-runtime-and-exit.json`、
`vnext/eval/evidence/phase85-shared-narrative-quality.json`、
`vnext/eval/evidence/phase86-packaged-parent-exit-cleanup.json`、
`vnext/eval/evidence/phase87-android-world-archive-parity.json`、
`vnext/eval/evidence/phase88-android-world-export-entry.json`、
`vnext/eval/evidence/phase89-desktop-loading-stage-parity.json`、
`vnext/eval/evidence/phase90-android-action-mode-boundary.json`、
`vnext/eval/evidence/phase91-player-surface-technical-leakage.json`。phase91 已从桌面游玩、桌面/Android
World 入口和桌面创建确认中移除 revision、内部 ID 等技术字段，并由共享资源名称映射显示背包物品；当前 Android P0 计为 85，
尚不能达到发布门槛。

phase92 又把正式结局从“文本 + 回合数”补齐为玩家回顾：最终路线、持有物品、人物关系和最近三次
关键行动在桌面与 Android 使用同一共享 Python presentation 投影显示。证据见
`vnext/eval/evidence/phase92-formal-ending-recap-parity.json`；两端产物已重建，但安装后视觉验收仍不以自动化替代。

phase93 统一了三端共享玩家术语：主路径使用“本机游戏服务、世界、内容版本、旅程、本机规则、本机存档”；
Host、SQLite、Python、loopback 和 schema 等实现词只留在高级诊断或高级创作边界。证据见
`vnext/eval/evidence/phase93-player-language-parity.json`。

phase94 按 Web Interface Guidelines 补齐桌面跳过导航、可见焦点、模型 Probe live announcement、关键表单
输入元数据和离线字体边界，并移除 Android 新旅程弹窗的强制 autofocus；后端新增防回退测试。证据见
`vnext/eval/evidence/phase94-offline-keyboard-accessibility-boundary.json`。

phase95 清除桌面模型草稿中的开发者局域网 IP/Huihui 默认值，首次启动直接展开中性本机模型配置；
桌面和 Android 切换 provider 时同步更新完整协议预设，预设由 Experience Contract 锁定；桌面设置与
AI 创作复用同一 `ModelProfileEditor`。证据见
`vnext/eval/evidence/phase95-model-first-run-provider-parity.json`。

phase96 修复了 embedded runtime 的回滚记录语义：安卓结局回合数、最近行动和历史入口现在与桌面一致，
旧本地库启动时会兼容补齐 `kind`。同时恢复 authenticated OpenAI-compatible 能力：桌面 API Key 进入系统
密钥链，Android 进入 `flutter_secure_storage`，SQLite、Run export 和 portable bundle 不保存明文，Probe、
AI 起草和回合请求只在内存中注入 Authorization。证据见
`vnext/eval/evidence/phase96-rollback-and-credential-boundary.json`。

phase97 为 AI 世界起草补上了与回合相同的请求身份和取消边界：桌面和 Android 在生成期间显示“取消本次起草”，后端/embedded runtime 只在进入校验前接受取消；模型晚到的结果会被丢弃，不会创建 World、Run 或半成品存档。证据见
`vnext/eval/evidence/phase97-draft-cancellation-boundary.json`；本次重新构建的 Android APK SHA-256 为
`25e21ffdc0f8c44d8a0c3ee595c46a04016bd31a3778cb8c6c1a2779c5f49c14`，macOS arm64 DMG SHA-256 为
`b1145d46a08eb6ddaa085b4f2e933da1d922e7c6950ad74a1b9987b668a9fdb6`。

phase98 又补齐了取消请求自身失败时的恢复语义：起草会立即停止等待并使晚到草案失效；正在处理的回合不会被假装取消，而是保留操作状态并说明旅程仍在处理中。Android widget 覆盖了起草取消传输失败和回合取消传输失败，证据见
`vnext/eval/evidence/phase98-cancellation-transport-recovery.json`。

phase99 修复了发布工作流的真实依赖边界：macOS 和 Windows clean runner 在构建 sidecar 前都会安装声明的
`.[dev,package]` extra，避免仅因开发机全局存在 PyInstaller 而让 release 误绿。证据见
`vnext/eval/evidence/phase99-release-sidecar-dependency-gate.json`。

phase100 将归档语义补到玩家入口：桌面和 Android 仍可查看已归档世界中的既有旅程，但 Continue 和 New Run
均明确禁用，必须先恢复世界才可游玩；这避免玩家点击后才收到后端拒绝。证据见
`vnext/eval/evidence/phase100-archived-world-view-only-boundary.json`。

phase101 为桌面和 Android 补上了 pending Run-operation 恢复标记：异常退出后重开会直接回到记住的 Run，
清理未完成标记，并明确告知玩家没有写入半个回合；正常完成、失败或接受取消都会清理标记。只保存布尔状态，
不保存叙事、请求内容或凭据。证据见 `vnext/eval/evidence/phase101-interrupted-run-recovery-marker.json`。
phase102 又修复了桌面导入世界/复制旅程后未持久化 active Run 的恢复缺口，并将 active Run key 操作收敛为可测试 composable。证据见 `vnext/eval/evidence/phase102-imported-run-recovery.json`。
phase103 将桌面自由行动和故事选择都接入 local-host SSE：模型生成中的玩家可见叙事会增量显示，只有 `turn_completed` 后才重新读取并展示已保存 Run；失败仍回到可重试状态，后端 choice stream 复用同一状态裁判和提交边界。证据见 `vnext/eval/evidence/phase103-desktop-narrative-stream.json`。
phase104 将桌面 portable 导入的重复 ID、模板覆盖和报告合并提取到纯函数模块，页面只保留状态/导航编排；独立边界测试已通过。证据见 `vnext/eval/evidence/phase104-portable-content-boundary.json`。
phase105 将模型超时/连接失败收敛为桌面和 Android 共享的玩家错误契约：Probe 明确等待 10 秒，叙事/草案明确等待 120 秒，并说明未写入结果、重试/换更快模型等恢复动作；Android 也不再暴露 Python 异常类名。证据见 `vnext/eval/evidence/phase105-player-model-timeout-feedback.json`。
phase106 首次把当前 DMG 的 WebView 窗口作为独立 gate 实测：在 macOS 26.3.1 上从构建包和只读挂载的 DMG 启动时，sidecar 和 `/health` 正常，但主进程在 WindowServer/System Events 中始终是 0 个窗口，因此当前 macOS 安装包玩家入口判定为 P0 fail。同时修复了 Vite 监听 `::1`、Tauri 等待 `127.0.0.1` 导致 `tauri dev` 无限等待的独立问题。证据见 `vnext/eval/evidence/phase106-macos-packaged-webview-window-gate.json`。
phase107 又在隔离副本中编译并运行 Tauri 2.11.5 / tao 0.35.3 / wry 0.55.1，仍得到进程存活、sidecar health 正常但 0 个 WindowServer 窗口；旧版 `/Applications/dzmm.app` 和 Calculator 控制应用在同一会话也无法被窗口枚举。因此 macOS gate 继续保持未通过，但根因尚不能归因到 DZMM 生命周期代码，暂不引入猜测性 native hack。证据见 `vnext/eval/evidence/phase107-macos-window-control-experiment.json`；下一次有效验收需要已知控制应用可见窗口的正常 macOS GUI 会话。
phase108 又把模型“测试连接”纳入三端操作反馈边界：桌面使用共享 OperationStatus 显示连接/等待阶段、耗时和终态；Android 模型页显示同一组阶段和耗时，返回后保留可用/未通过结果。证据见 `vnext/eval/evidence/phase108-model-probe-loading-parity.json`；桌面 27 项测试、Flutter 20 项测试、分析和构建均通过；phase109 后桌面测试增至 28 项。
phase109 将桌面模型档案列表从根 `App.vue` 提取为 `ModelProfileList.vue`：列表摘要、默认标记、Probe 结果和 CRUD 事件现在有独立的 typed component boundary，根页面只保留 use-case 编排；新增组件测试覆盖动作 payload。证据见 `vnext/eval/evidence/phase109-desktop-model-list-boundary.json`；桌面测试增至 28 项、共 12 个测试文件，构建通过。
phase110 修复了 Android 自由行动与桌面规则能力不一致的缺口：当世界存在多个地点时，Android 现在显示目的地选择并在 `narrate` 前提交同一 Python 校验的 `move` 命令；单地点世界仍保持简洁输入。证据见 `vnext/eval/evidence/phase110-android-free-action-destination-parity.json`；Flutter 20 项测试和分析通过。
phase111 又把桌面目的地选项从硬编码港口/灯塔改为当前 Run presentation 的全部地点，并在重开/回读时校正过期目的地；Android 和 desktop 现在共享同一 World location 映射。证据见 `vnext/eval/evidence/phase111-destination-presentation-parity.json`；桌面测试增至 29 项，构建和 Flutter 20 项测试均通过。
phase112 进一步统一单地点世界的玩家界面：desktop 与 Android 都隐藏无意义的目的地控件，多地点世界仍保留动态地点选择。证据见 `vnext/eval/evidence/phase112-single-location-action-parity.json`；桌面测试增至 30 项，构建通过。
phase113 修复跨 Run 的重试状态泄漏：桌面和 Android 在进入另一段旅程时都会清除捕获旧 Run 的重试动作，避免失败后的旧选择/行动被误提交到新旅程；桌面和 Android 新增纯边界测试。证据见 `vnext/eval/evidence/phase113-retry-run-boundary.json`；桌面 32 项测试、构建和 Flutter 21 项测试通过。
phase114 修复桌面 `App.vue` 组件抽取后的无障碍回归：顶层玩家通知恢复 `role=status` 与 `aria-live=polite`，保存、取消、重试和恢复反馈会继续被键盘/辅助技术感知；Host 故障仍保持 alert。证据见 `vnext/eval/evidence/phase114-desktop-notice-live-region.json`；后端 112 项与 Ruff、桌面 32 项/构建、Flutter 21 项/analyze 均通过。
phase115 将 Android OperationStatusCard 补为显式 TalkBack live region：阶段、耗时和“模型可能仍在加载”的反馈不再只依赖视觉文本；新增 Semantics 测试。证据见 `vnext/eval/evidence/phase115-android-operation-live-region.json`；Flutter 22 项测试/analyze、桌面 32 项/构建和后端 112 项/Ruff 通过。
phase116 生成了包含 phase113–115 修复的最新 Android debug APK（SHA-256 `1b108e7bcfbd77d1e879f45b08d092d76b83ae4cd58fac15dd32a15312624dfe`）和 macOS release `.app`；`tauri build --bundles app` 通过，但完整 DMG 在当前环境的 `bundle_dmg.sh` 最后一步失败，因此旧 DMG 不作为最新产物替代。证据见 `vnext/eval/evidence/phase116-latest-package-artifacts.json`。
phase117 启动了 `dzmm-ux-api36` Android 模拟器并安装最新 APK，通过 `adb reverse tcp:11434 tcp:11434` 连接本机 Ollama；默认 `qwen2.5:7b` Probe 返回可用。模拟器保留既有测试世界并停在 World 列表，交由玩家人工体验；这不是物理 Android A-F 或 30 回合完成证据。证据见 `vnext/eval/evidence/phase117-android-emulator-qwen7b-session.json`。
phase118 按玩家反馈重排 Android 游玩界面：历史叙事留在唯一主滚动区，最新场景、操作阶段和选项/自由行动输入固定在底部；常驻状态进入可收起的“当前状态”，状态反馈和回合记录进入独立的“事件与行动记录”。Flutter analyze、22 项测试和 APK 构建通过；新 Run 在模拟器中已安装并人工确认开场叙事与底部选项可见。APK SHA-256 为 `80706d7e2242e1ea158b21dafd7fd435e4c20ed2259c818cfd80a2c731e8860b`。phase118 当时核实剧情仍是固定规则图 + 模型正文；该边界已由 phase119 的每 Run 变化契约继续推进。证据见 `vnext/eval/evidence/phase118-mobile-play-surface-and-plot-boundary.json`。
phase119 参考老版 DZMM 的 GM 回合边界，补上 vNext 的叙事变化契约：章节/选项继续由 Python 校验硬效果，但章节选项不再阻断 `narrate`/`move` 自由行动；每个 Run 以独立 Run ID 作为变化种子，保存最近 6 回合的玩家输入、叙事和机械结果，向模型注入新的场景/NPC/线索压力点；Ollama、LM Studio 和 OpenAI-compatible 叙事请求启用非零采样。后端全量 113 项测试和 Ruff 通过，新增自由行动与 `narrative_context` 回读断言。证据见 `vnext/eval/evidence/phase119-emergent-gm-narrative-contract.json`。当前仍需用本地 qwen 7B 重开同一世界两次，人工确认不同 Run 的剧情钩子、NPC反应和可追查线索出现差异；硬状态/结局一致性仍由 Python 规则边界负责。
phase120 按老版 DZMM 的运行时概念补齐 Next 第一批世界运行层：RunState 新增地点访问状态、NPC 动态状态、活跃世界事件、剧情线容器和待回应互动；NPC 在叙事中被遇见/发言后会被 Python 记录，满足地点/相遇/冷却条件时排队一次主动联系；预定义世界事件支持按回合门槛激活；StoryBeat 和桌面/Android 支持多段结构化 NPC 对话与主动事件反馈。后端全量 116 项测试、Ruff、桌面 32 项测试/构建、Flutter 22 项/analyze 通过。最新 Android APK SHA-256 为 `1338c8fc5be88440191a979c5449689f11e867d519e9032cc9021d287aa39aed`，已安装到 `emulator-5554`。证据见 `vnext/eval/evidence/phase120-world-runtime-npc-initiative.json`。尚未实现 LLM 结构化 `gm_actions` 对剧情线/隐藏事件的自由创建与解决，下一阶段再接入 Python allowlist。
phase121 将 `gm_actions` 接入 desktop 与 embedded 两条回合链路：模型可在不可见尾部标记中提出新剧情线、隐藏事件及其解决意图；Python 只接受有限类型、合法 ID、长度/枚举/目标检查，重复或越权动作不会写入 RunState。正文清洗、流式增量、旧 narrator seam 和取消/失败零写入语义保持兼容。后端全量 117 项测试、Ruff、desktop 32 项/构建、Flutter 22 项/analyze 通过；Android debug APK 已重新构建，SHA-256 为 `1a77b99d4c10110930e327e52ae33a90befc91614c4a15db803ff0dfa71675d6`，但当前 adb 无在线设备，尚未安装。证据见 `vnext/eval/evidence/phase121-gm-actions-allowlist.json`。
phase122 扩展 AI 世界草案的安全创作边界：模型可以提供 NPC、势力、世界事件和地点连接；Python 负责安全 ID、数量/长度/枚举限制、地点引用解析，并将角色卡同步为可跟踪的运行时 NPC。embedded 生成失败的安全骨架也保留描述性 NPC/事件/势力，不再把所有动态实体丢弃。后端全量 119 项测试、Ruff 通过；Android debug APK 已重新构建，SHA-256 为 `3171ba53f5c9dfa26f2b131efdd2357fb09b9d9a7922f54ef682897b1f374409`，但当前 adb 仍无在线设备。证据见 `vnext/eval/evidence/phase122-ai-world-runtime-material.json`。
phase123 将老 DZMM 的结构化事件谓词迁移到 Next 的纯 RunState：支持地点到达、NPC 状态、物品拥有、旗标、势力张力和 `all/any` 组合；势力按回合由 Python 增长并限幅，事件满足 `trigger_conditions` 后才激活，同一 revision 不会重复推进。LLM 只看到状态并提出叙事，不获得直接写入权。后端全量 120 项测试、Ruff 通过；Android debug APK SHA-256 为 `26fc9e2f24bfacb99a03fe34840d66f4b6ee2c16715a204d62ab4ffb976075e6`，当前 adb 无在线设备。证据见 `vnext/eval/evidence/phase123-runtime-event-predicates.json`。
phase124 又补上老 DZMM 的事件完成和 Campaign/Phase 最小运行层：事件可声明 Python 可验证的 `completion_conditions`，完成后进入 resolved；Campaign 记录当前阶段、已完成事件和已完成阶段，并在关键事件达到 required_count 后推进下一阶段；NPC 运行时状态补上所属势力与初始声誉。事件、阶段和势力状态同时注入 GM 上下文。后端全量 121 项测试、Ruff 通过；本地 `dzmm-ux-api36` Android 36 模拟器已启动，最新 APK 已安装并成功打开 `local.dzmm.dzmm_next_mobile/.MainActivity`，SHA-256 为 `9b8f667cee1209e50b30cbd65421420fb52ee086f2296bf751f54f4fcb161ce8`。证据见 `vnext/eval/evidence/phase124-campaign-event-completion-emulator.json`。
phase125 用本地 `dzmm-ux-api36` 模拟器接入本机 `qwen2.5:7b` 完成了 3 回合玩家旅程：Loading 阶段可见，模型缺少结构化 `available_choices` 时 Android 不再因快照投影异常停在旧画面，而是安全进入自由行动分支；最终正式结局摘要正常显示，并从同一 World 成功开始新 Run、显示新的开场叙事和选项。进一步用相同世界和相同首个选择重开第二个 Run，Qwen 7B 生成了不同的叙事，并出现沈砚主动联系、灰潮线索和新的回应钩子。Flutter 24 项测试、analyze、APK 构建通过；APK SHA-256 为 `874ec1d5dfd21b42077c7f6d0ef434e70684f548bf0c7b371faaa278ce7cd9aa`。本地模拟器证据下玩家评分由 78 提升至 85（+7）；证据见 `vnext/eval/evidence/phase125-local-emulator-qwen7b-player-journey.json`。下一轮只继续做高收益 P1；若评分不再明显提升则结束 Goal。

phase126 改为从零创建新世界验收，而不是复用既有世界：Android AI 世界向导通过本机 Qwen 7B 生成“潮汐之门”，保留 2 个角色、2 个地点、4 个运行时 NPC、2 个势力和 2 个事件素材；针对 7B 容易输出 `chapter_1` 紧凑 JSON 的事实，embedded world draft 使用紧凑素材协议和较小输出预算，Python 再映射到受控 hybrid 规则骨架。新世界开场已实测显示生成地点“月光港”、角色“艾莉/杰克”和对应推荐“援手艾莉 / 替杰克保守秘密”；首个选择后，Qwen 正文引用“月光港、艾莉、老渔夫汤姆”和小巷线索，并触发“艾莉主动找到了你”的待回应互动，下一组推荐也跟随生成角色重写。另修复主角与首角色同名时开场对话自言自语的边界，并补充 compact story、描述性 NPC 和 opening speaker 测试。后端 126 项测试、Ruff、Flutter 24 项/analyze、APK 构建通过；最新 APK SHA-256 为 `15e9be4a358c4bb4c9002cd978391c0510e4c424addb561ce2336ba6748069a7`。玩家评分 85→86（+1）；证据见 `vnext/eval/evidence/phase126-new-world-qwen7b-quality.json`。当前剩余主要是“模型素材 + Python 规则骨架”的边界、Android 草案摘要信息层级和三端安装包验收，不再把本轮 Goal 扩展为大规模视觉重构。

phase127 在同一条玩家路径上继续收口：Android AI 世界草案确认前新增生成素材摘要，明确展示地点、角色/NPC、势力、事件，并说明本机 hybrid 规则接管边界；Flutter widget test 覆盖摘要和确认前零写入。随后用本机 Qwen 7B 从零创建“潮汐之门”新世界，完成 3 回合并持久化正式结局，再从同一 World 开始新 Run。叙事上下文改为向模型提供生成实体的玩家名称、章节/结局显示标签和禁止内部 ID/旧模板名的 guardrail；复测中正文使用“艾莉森、墨菲斯托、老船长”并触发主动 NPC 联系，不再把内部关系 ID `lan` 写成旧名“兰”。后端 127 项测试、Ruff、Flutter 23 项/analyze、APK 构建通过；最新 APK SHA-256 为 `e84207e9592fc90bf1d30008d50d5a97ea50c364a542c4b788de4d5270e8063b`。玩家评分 86→87（+1）；证据见 `vnext/eval/evidence/phase127-next-goal-draft-review-and-context-grounding.json`。本 Goal 到此停止：剩余主要是 Windows/macOS/Android 发布环境与真机验收门槛。

phase128 处理本轮玩家反馈的整组 P0/P1：世界详情新增永久删除入口，删除会级联旅程、回合和历史并要求二次确认；Android 操作阶段改为单行横向滚动；草案审阅只显示玩家可理解的素材摘要和可玩性结论，不再暴露 `mechanics`/`canonical` 等修复路径，不可玩草案阻止创建。安全世界映射清理雾港 lorebook、雾灯和旧章节文本，叙事上下文改为当前世界的生成实体；离线模板则明确标注为固定雾港示例。Android 游玩页把历史、当前新内容和选项拆成独立阅读区域，长正文可展开全文；当前卡片的折叠阈值进一步收紧后，模拟器截图已同时看到长文摘要和底部选项。后端 129 项测试、Ruff、Flutter 24 项/analyze、桌面 32 项/构建通过；最新 Android debug APK SHA-256 为 `cff89639321830fd338072fec48e33fd42ad50689226a0edadb32fc19ca338b1`。本地 `dzmm-ux-api36` 已安装并打开该 APK；PC-qwen3-direct 本轮在 120 秒内无返回，界面正确保留单行等待状态且未写入半成品，离线模板草案审阅流程正常。玩家评分暂不变，交由用户用响应的 Qwen 配置人工验收新世界叙事关联性和长历史滚动。证据见 `vnext/eval/evidence/phase128-player-feedback-world-integrity-and-mobile-reading.json`。

phase129 按玩家体验 Goal 连续做了三轮可感知改进：当前回合先显示主要结果并把其他变化收进可展开入口；叙事请求增加最近行动、未完成剧情线、活动事件和按关键词触发的世界书分层记忆；Android“当前状态”集中展示地点、路线、物品、人物关系和线索；NPC 主动联系时紧凑当前卡仍保留“正在等待回应”和下一步提示。真实模拟器截图、回合状态面板和 NPC StoryBeat 契约均有证据；后端 132 项测试、Ruff、Flutter analyze/24 项测试、APK 构建通过，最新 APK SHA-256 为 `e3f1b3b679e3a88f2c5e947bb720ac963c42f059436c76e5693b50e5fc8742ad`，已安装至 `emulator-5554`。玩家体验评分由 87 提升至 90（+3）；本轮未触发连续两轮无提升，后续若新世界真实体验连续两轮不加分则停止 Goal。证据见 `vnext/eval/evidence/phase129-player-experience-goal.json`。
phase130 以本地 `dzmm-ux-api36` 模拟器和本机 `qwen2.5:7b` 从创建新世界开始验收：修复 Android 保存模型后的 `setState` 异步回调 P0，并以 commit `699b325` 推送；模型 Probe 最终返回“可用 · protocol response contains content”。新世界草案/开场/前两回合中，地点、角色、NPC 主动联系、线索、路线锁定和下一步选项保持可理解因果；第三回合显示模型截断边界但未写入半回合，随后世界详情与正式好结局页可回顾 3 回合、关键行动、关系/物品，并成功从同一世界创建新 Run。Flutter analyze 和 24 项测试通过，APK SHA-256 为 `bc4600db200c5357d13eb7e03c3ee5535582a265d7991f32d0362a792819b92f`。玩家评分 90→91（+1）；10–30 回合长局、不同题材去模板化和三端安装证据仍未通过。证据见 `vnext/eval/evidence/phase130-new-world-qwen7b-longrun-replay.json`。
phase131 修复 AI 世界三章即结束的长局阻断：桌面 AI 草案与 Android embedded 安全映射共用 `extend_story_for_long_run`，三章 compact story 扩为 `ch1`–`ch10`，中间章节只提供地点追查/NPC 询问桥接选项，最后一章才允许结局；离线固定雾港模板保持兼容。后端 132 项测试、Ruff、Flutter 24 项/analyze 通过；最新 APK SHA-256 为 `d73306bdba9f365263fd8443272db9986fbceb41d739af7adc4ffd7a102d13e1`，已安装模拟器。新世界真实 Android 验收第三回合仍显示“线索推进 2”和两个下一步选项，玩家评分 91→92（+1）；完整 10–30 回合、不同题材和三端安装包证据仍待完成。证据见 `vnext/eval/evidence/phase131-ai-world-long-run-extension.json`。
phase132 将 Legacy 边界变成玩家可见的设置说明：macOS/Windows 与 Android 都明确旧版 DZMM 存档不会自动迁移或覆盖 Next，跨设备通过世界包/旅程快照主动携带；Android widget 测试覆盖该提示，桌面 32 项测试和生产构建通过。该轮没有改变核心游玩能力，玩家评分保持 92；完整长局、不同题材与三端冷启动/恢复证据仍是发布门槛。
phase133 用当前代码重新构建 PyInstaller sidecar 和 macOS release `.app`，从实际应用二进制冷启动后 `/health` 返回 `app=dzmm-next`、`api_version=2`、`storage=local`、`foreign_keys=true`；桌面 32 项测试、生产构建和 sidecar package smoke 通过。Windows 原生 installer、Android 真机/发布包仍未验证，玩家评分保持 92。phase132 与 phase133 连续两轮无明显提升，按 Goal 退出机制停止继续改动。证据见 `vnext/eval/evidence/phase133-macos-package-health.json`。

### Portable bundle slice

- 后端提供显式 `world export/import` 与 `Run export/clone`；导入/克隆始终生成新的 aggregate/Run ID，
  不携带模型凭据，也不自动同步。
- 桌面设置页提供世界包、Run 快照导出以及 JSON 导入入口；Android 设置页也提供 Run 导出和 JSON
  导入/克隆，`LocalHostPort` 与 embedded core 已声明同一组操作；phase61 已在 Android 取 Run
  export→system picker→clone→重开回读证据。

证据：`vnext/backend/tests/test_portable.py`（world round-trip、Run clone 与损坏包拒绝），桌面生产构建通过；
Android direct model 与 portable 取证见 `vnext/eval/evidence/phase59-android-direct-model-probe.json`、
`vnext/eval/evidence/phase61-android-portable-roundtrip.json`。
损坏包零写入已有后端保护；Android↔desktop 双向安装后 UI 取证仍是 P0 缺口。

## Phase 134：Qwen 7B 长局与移动端操作区复验

本机 Qwen 7B 已从新世界创建开始完成 10 回合并正式结局；Android 长正文操作区修复为正文内部滚动、选项固定在底部，并提高 Ollama 生成预算、清理 Qwen Markdown/选择元话术。玩家评分暂为 93/100。不同题材世界、Android release/真机和 Windows 原生安装仍未通过；若后续两轮评分无提升，停止本 Goal。
证据见 `vnext/eval/evidence/phase134-qwen7b-long-run-and-mobile-action-layout.json`。

phase135–136 尝试不同题材和复核发布 gate，但没有取得可复核的新玩家分值；连续两轮保持 93，按退出机制停止本 Goal。后续需在可控输入环境、Android release/真机和 Windows 原生环境补齐证据后再开启新 Goal。
证据见 `vnext/eval/evidence/phase135-genre-and-release-gate-review.json`、`vnext/eval/evidence/phase136-no-score-exit-review.json`。

## Phase 144：替换旧版的工程安全网与 cutover 决策

本轮没有改变玩家可感知的剧情或布局，因此评分保持 **93/100**，不计入新的玩家体验加分。
为后续把 vNext 作为唯一 DZMM 做准备，新增 `ADR-010-single-dzmm-cutover.md`，明确采用
“先通过发布 gate、再统一命名、归档旧版、最后删除旧版实现”的受控 cutover，而不是长期双线
维护或立即不可逆删除。

工程侧新增 `.github/workflows/backend-ci.yml`，在 PR 和 `main` push 上固定安装 backend dev
依赖、Ruff 与 pytest；桌面 SSE 解析抽为共享 `consumeSseStream`，补齐 CRLF、跨 chunk 和无尾
分隔符测试；桌面回合与 AI 世界起草请求现在传递 `AbortSignal`，切换世界/设置、取消或卸载时
会中止旧请求，避免旧 Run 的迟到事件污染新页面。后端 136 项测试、Ruff、桌面 34 项 Vitest
与生产构建、Flutter 25 项测试与 analyze 均通过。

反馈逐项映射见 `docs/reviews/2026-08-30-cutover-readiness.md`。当前仍阻塞替换的事实是
macOS 可见 WebView/完整安装包旅程、Windows 原生 installer 旅程、Android release 冷启动/恢复
以及统一正式命名和旧版归档策略；在这些门槛通过前不合入 `main` 或删除老版代码。

## Phase 145：用户可见名称收敛

在不改变内部包标识、数据库目录或 sidecar 文件名的前提下，桌面窗口/HTML 标题、Tauri 产品名、
Android 应用标题与系统标签、后端描述和相关 README 已统一为 **DZMM**，不再让玩家看到“Next”
或“Preview”作为第二产品线。内部 `dzmm_vnext`、`dzmm-next-*` 和旧数据目录仍暂留，直到发布
gate、升级兼容和回滚策略确认后再迁移；因此这轮不计玩家体验加分。

验证：cargo check、桌面 34 项测试与生产构建、Flutter 25 项测试与 analyze 通过。正式包名、
sidecar 名、默认数据目录和 `main` 合并仍是 cutover 阶段工作，不在本轮执行。

随后复核 macOS PyInstaller sidecar：当前代码可完成 clean build、sidecar `/health` smoke，且
release workflow 的 macOS/Windows 资源检查已与实际 `dzmm-next-backend` 产物一致；这只证明
打包依赖边界，不等同于 macOS 可见 WebView 或 Windows 安装后玩家旅程通过。模拟器当前未在线，
因此本轮没有新增 Android 真实旅程分数。

## Phase 146：当前发布环境复核

当前 worktree 已成功生成 `DZMM.app`，Info.plist 的展示名为 `DZMM`，包内 sidecar 资源存在；
clean sidecar build 与 health smoke 通过。Android 模拟器经直接启动后已在线，当前 DZMM debug APK
已安装并打开 `MainActivity`，但本轮没有重新跑完整 Qwen 旅程，因此玩家评分仍为 **93/100**；
Windows 原生 installer 仍不在本机可用环境中。证据见 `vnext/eval/evidence/phase146-package-and-emulator-gate.json`。

这不是 Goal 退出条件：阻塞点从代码缺陷转为可控的发布/观察环境。下一步安全动作是使用已知可见
窗口的 macOS GUI 会话、Windows runner 和在线 Android 模拟器补齐主旅程证据；在此之前不删除旧版
实现，也不把内部 `dzmm_vnext`/`dzmm-next-*` 标识直接改成不可兼容的新包标识。

为降低后续命名切换风险，桌面 active Run、pending operation 和主题设置已改用 `dzmm-*` 新键，
并对 `dzmm-next-*` 旧键提供一次性兼容迁移；36 项桌面测试与生产构建通过。这是可回滚的数据边界
改进，不改变玩家评分。

## Phase 148：修复打包数据库迁移阻断

重新启动 macOS 包时发现真实迁移错误：旧本地库记录的 `0011_lifecycle_audit_events` 在当前
迁移资源中不存在，sidecar 因此退出。新增窄范围回锚逻辑，只在 `alembic_version` 精确匹配该
旧 revision 且 `lifecycle_audit_events` 表存在时改为现行 `0009_lifecycle_audit_events`，随后
正常执行到 `0012_model_credentials`；其他数据库版本保持不变。复制当前本地库做迁移回归已通过，
后端 137 项测试与 Ruff 全绿。证据见 `vnext/eval/evidence/phase148-packaged-migration-repair.json`。

这是安装/升级可靠性修复，玩家评分仍为 **93/100**。下一步重新构建并启动 DZMM 包，确认旧版
端口共存时 Host 能就绪；完整玩家旅程、Windows installer 和 Android release 仍是替换门槛。

## Phase 149：最新 macOS 包启动与旧存档迁移复核

按正确顺序重建 PyInstaller sidecar 和 `DZMM.app` 后，新包在旧版进程继续占用 8765 的情况下
成功启动，自动选择 `127.0.0.1:50909`；持久化 `dzmm.log` 记录了旧 revision 回锚并完成到
`0012_model_credentials`，`/health` 返回 `app=dzmm-next`、本地存储和外键开启，世界列表 API
返回空数组而非启动错误。证据见 `vnext/eval/evidence/phase149-packaged-macos-startup.json`。

本轮仍不增加玩家分数（**93/100**），因为没有新的完整创建→游玩→结局旅程。macOS 的安装启动
阻断已解除，但可见 GUI 主路径仍需观察，Windows 原生 installer、Android release 冷启动/恢复
以及三端完整玩家旅程仍未完成，因此不进入老版代码删除或 `main` 合并。

## Phase 150：Android release 模拟器冷启动复核

在 `dzmm-ux-api36`（API 36，`emulator-5554`）上构建并安装 `app-release.apk`，强制停止后重新
启动 `MainActivity` 成功，系统顶层 Activity 可见；截图确认品牌为 DZMM，当前内容、历史/重新
读取入口和底部选项同时可见。证据见 `vnext/eval/evidence/phase150-android-release-cold-start.json`。

本轮仍保持 **93/100**：只是 release 冷启动和布局证据，没有新增完整玩家旅程。Android 真机、后台
恢复/失败重试、30 回合 Qwen 旅程和 Windows 原生 installer 仍是替换门槛。

## Phase 151：修复 macOS 回退端口返回值错配

可见 macOS 包曾在 sidecar 已健康监听回退端口时仍显示 Host 未就绪。根因是 Tauri 启动 sidecar
和返回给前端的 origin 各自重新计算端口；旧版占用 8765 时两次结果不同。现在由 `start_runtime`
计算一次端口并返回实际 origin，前端轮询与 sidecar 使用同一地址。`cargo fmt --check`、`cargo check`、
桌面 36 项测试通过；重建并启动包后，sidecar 在 `127.0.0.1:53308` 健康，窗口显示“本机游戏服务
已就绪”，日志记录 `/health` 和模型列表请求均为 200。证据见
`vnext/eval/evidence/phase151-macos-host-port-return.json`。

这是首屏可玩性/跨端安装可靠性的实际提升，玩家评分由 **93/100 提升至 94/100**；尚未证明该
安装包的完整创建世界→游玩→结局→新 Run 旅程，Windows installer 和 Android 后台恢复仍待验证。

## Phase 152：Windows release CI 与 installer smoke

将隔离分支同步到远端并触发 release workflow 后，首次 Windows runner 在读取含中文的
`release.yml` 时因 cp1252 编码失败；测试改为显式 UTF-8 后重新运行成功。run
`33299415557` 的 Windows job 完成 137 项后端测试、PyInstaller sidecar、Tauri NSIS 构建，
installer 内容检查确认 `dzmm-next-backend.exe` 与 Python `_internal` 存在，打包 sidecar 的
Local Host `/health` 也通过；同一 run 的 macOS job 完成 DMG `.app + backend + _internal` smoke。
artifact 为 `dzmm-windows-x64`（22,770,763 bytes）和 `dzmm-macos-arm64`（31,012,067 bytes）。
证据见 `vnext/eval/evidence/phase152-windows-release-ci.json`。

这轮只证明构建与安装包内容，未在 Windows 桌面上执行安装后可见玩家流程，因此评分保持
**94/100**。Windows 安装后完整创建世界→游玩→结局→新 Run、Android 后台恢复/真机和
跨端回读仍是替换门槛。

## Phase 153：Android release 强制停止后恢复

在 `emulator-5554` 上对 release APK 执行 `am force-stop` 后重新启动 `MainActivity`，系统顶层
Activity 恢复成功；截图显示 DZMM 游玩页仍保留当前场景、叙事内容、历史重新读取入口和底部
操作。证据见 `vnext/eval/evidence/phase153-android-release-recovery.json`。

本轮没有新的完整创建/游玩旅程，评分保持 **94/100**。Android 真机、模型失败重试、跨端回读和
Windows 安装后的玩家路径仍未完成。

## Phase 154：macOS 打包版 Qwen 7B 玩家闭环（API 证据）

在重建的 DZMM.app sidecar 上配置本机 Qwen 7B，通过打包 API 创建雾港世界，连续执行
`rescue-lan → lan-testimony → open-tide-gate` 三次选择，得到 `lan-dawn / good` 正式结局
（revision 3、4 个 story beats），随后从同一 World 创建第二个 Run，并成功重开回读 opening
（revision 0、1 个 opening beat）。三次模型叙事调用均返回 201，耗时约 21.9/23.1/30.7 秒。
证据见 `vnext/eval/evidence/phase154-macos-packaged-player-loop.json`。

这证明 macOS 打包 sidecar 的真实模型生命周期可完成，但本轮通过 API 而非可见 GUI 点击，故玩家
评分保持 **94/100**。仍需桌面可见创建/游玩/结局/新 Run、Windows 安装后 GUI、Android 真机
及跨端回读证据。

## Phase 155：macOS 可见 GUI 观察权限边界

尝试通过桌面 GUI 自动化读取 DZMM 窗口时，系统返回 `Computer Use permissions are not granted`。
因此 phase154 的打包 API 闭环和现有窗口截图不能被扩大解释为完整可见 GUI 验收；本轮评分保持
**94/100**。待用户接管或授予 GUI 观察权限后，继续验证桌面创建/选择/结局/新 Run；其余
Windows 安装后 GUI、Android 真机和跨端回读门槛不变。证据见
`vnext/eval/evidence/phase155-macos-gui-observation-boundary.json`。

## Phase 156：Android 模型端点可达性提示

Android release 模拟器的真实操作暴露出一个此前被 API/冷启动证据掩盖的 P0：已保存模型档案使用
`127.0.0.1:11434` 时，模型请求失败，页面虽然保持零写入并提供重试，但玩家不知道模拟器中的
`127.0.0.1` 不是电脑。模型设置现在按平台提供默认地址：Android 模拟器使用 `10.0.2.2`，桌面
仍使用 `127.0.0.1`；已有 loopback 档案会显示迁移提示，并说明真机局域网 IP 和服务监听要求。
Flutter analyze、相关 widget 测试、release APK 构建/安装均通过，截图确认提示在模型列表可见。
证据见 `vnext/eval/evidence/phase156-android-model-endpoint-guidance.json`。

这是设置可理解性和失败恢复的实际修复，但尚未增加玩家分数（保持 **94/100**）：Ollama 当前仅
监听宿主机 `127.0.0.1:11434`，Android release 尚未完成“配置可达模型→创建世界→完整游玩→结局→新
Run”的可见闭环。下一步先建立受控的宿主机可达模型端点，再重跑 Android release 主旅程；若分数连续
两轮无提升，则停止体验驱动改动，转入替换门槛审计。

## Phase 157：Android release 新世界完整玩家旅程

在宿主机 Ollama 临时监听 `0.0.0.0:11434`、Android 模拟器使用 `10.0.2.2:11434` 后，按玩家入口
创建了一个全新世界（地点为月影港/秘密岛屿，未使用雾港离线模板），审阅并确认草案，使用 Qwen 7B
完成 10 个可见回合。每回合都有叙事、NPC 主动联系、状态结果和可选行动；最终回合显示正式的隐藏
结局，重新进入已完成旅程可看到“10 个回合”、路线、关系与物品。回到世界详情后，界面显示该旅程已
完成，并在同一世界创建第二段旅程，看到新的主角和新的开场内容。证据见
`vnext/eval/evidence/phase157-android-release-new-world-journey.json`。

这是新的完整玩家闭环，评分由 **94/100 提升至 95/100**。Qwen 7B 在模拟器单回合约 35–90 秒，
虽然阶段和耗时反馈可见，但仍是明显的沉浸/节奏风险；真实 Android 设备、Windows 安装后 GUI、
macOS 可见 GUI 和跨设备回读仍未通过，因此不执行老版删除或 `main` 合并。

## Phase 158：Android release 真实旅程强制停止恢复

在 phase157 已完成的真实 10 回合隐藏结局上执行 Android release `force-stop` 并重新启动
`MainActivity`，应用恢复到第 10 回合、隐藏结局和结算内容，未丢失旅程状态。证据见
`vnext/eval/evidence/phase158-android-release-recovery-after-journey.json`。

这是持久化恢复的确认性证据，评分保持 **95/100**；不重复计分。下一步只处理尚未通过的
macOS 可见 GUI、Windows 安装后 GUI 和替换审计，不再以重复 Android 模拟器回归推动分数。

## Phase 159：Android 执行状态单行紧凑布局

真实 Android loading 截图显示阶段标签虽未换行，但右侧会被裁切，需要额外横向滑动。现在将四个
阶段改为等宽紧凑条，每个阶段在自己的单元格内单行显示并以省略号处理极窄空间；不再依赖隐藏的
横向滚动。Flutter analyze、相关 widget 测试和 release APK 构建均通过。证据见
`vnext/eval/evidence/phase159-android-operation-strip.json`。

这是对执行状态可读性的修复，评分保持 **95/100**，不重复计算已有 loading 能力。待 macOS/Windows
可见安装包 gate 可用后，再补一次真实生成操作的视觉确认。

## Phase 160：单一产品命名与数据边界审计

完成 `DZMM`、`dzmm-next`、`dzmm_vnext`、`.dzmm-vnext-v3`、sidecar 文件名、包标识和本地
存储键的引用清单，明确这些标识不能在迁移策略和桌面安装包验收前直接替换。清单见
`docs/reviews/2026-08-30-cutover-name-inventory.md`，结构化证据见
`vnext/eval/evidence/phase160-cutover-name-audit.json`。本阶段不改变玩家评分，且不执行旧版
删除；下一步是 macOS/Windows 可见 GUI gate 与迁移/回滚策略。

## Phase 161：桌面首次进入的存储边界提示

桌面启动后已有模型档案时，进入世界中心会显示本机独立存储提示，明确旧版 DZMM
不会自动迁移或覆盖，并指向主动导入世界包/旅程快照的路径；首次无模型仍优先引导模型
设置，恢复中的旅程提示不被覆盖。`npm run build` 通过。本阶段不改变玩家评分，仍需在
安装包 GUI 中确认提示与主流程的视觉位置。结构化证据见
`vnext/eval/evidence/phase161-desktop-storage-boundary-notice.json`。

## Phase 162：替换边界回归验证

桌面 13 个测试文件/36 项测试、后端 sidecar 与便携边界 13 项测试全部通过；覆盖新库迁移、
不兼容预览库拒绝、世界/旅程导入边界以及 active/pending Run 键兼容。仅有既存
Starlette/httpx 弃用警告，不影响结果。证据见 `vnext/eval/evidence/phase162-cutover-boundary-regression.json`。
本阶段评分保持 **95/100**，下一步仍是安装包 GUI 证据与迁移/回滚最终决策。

## Phase 163：首个替换版本迁移策略冻结

ADR-010 已冻结首个替换版本的迁移策略：不自动复制、覆盖或合并旧版数据库；保留隔离
数据目录，玩家通过世界包或旅程快照主动带入内容，源数据不被改写。桌面和 Android
均已有对应的玩家说明，sidecar 对不兼容预览库保持拒绝并零写入。该策略完成了“可理解的
不迁移边界”门槛，但旧版归档 tag、恢复演练和最终 cutover 仍未完成，评分保持 **95/100**。
结构化证据见 `vnext/eval/evidence/phase163-migration-policy-freeze.json`。

## Phase 166：运行时数据备份与恢复演练

新增回归测试，在临时 vNext 数据目录中创建可玩世界，执行 SQLite 备份、模拟数据库丢失、
恢复备份并重新启动 API，成功通过 `/api/v2/worlds` 回读世界。后端全量测试 **138 passed**，
仅有既存 Starlette/httpx 弃用警告；没有触碰真实用户数据。证据见
`vnext/eval/evidence/phase166-runtime-data-restore-rehearsal.json`。这是数据恢复演练，
仍不等同于 macOS/Windows 安装包 GUI 验收，评分保持 **95/100**。

## Phase 172：发布交接清单

新增 release handoff，固定当前候选、已完成证据、授权后推送/CI/Windows/macOS GUI 验收顺序，
以及最终 cutover 的命名、合并和删除约束。见 `docs/reviews/2026-08-30-release-handoff.md`。
本阶段不改变玩家评分，Goal 继续保持 active。

## Phase 174：当前候选 release workflow

已从推送后的当前候选运行 `33314492033`：macOS arm64 与 Windows x64 构建均成功，生成未过期
artifacts（分别约 31.0MB、22.8MB）；`release` 发布 job 因非 `v*` tag 按设计跳过。构建产物
现在可用于安装验收，但不能替代 Windows 原生 GUI 或 macOS 可见玩家旅程。证据见
`vnext/eval/evidence/phase174-release-workflow-current-candidate.json`，评分保持 **95/100**。

## Phase 175：GitHub 授权后 Draft PR 与校验闭环

用户已明确授权 GitHub 操作。当前候选已推送到 `feature/dzmm-vnext`，并创建
[Draft PR #2](https://github.com/b31o8321/dzmm/pull/2)（base=`main`，head=`80fd39f`）；
PR 保持 Draft，未合并、未删除旧版。PR 的 backend-ci 与 E2E smoke 均通过；E2E 之前因
Ubuntu runner 缺少 `gobject-2.0`/`gio-2.0` 失败，补充 `libwebkit2gtk-4.1-dev`、
`libappindicator3-dev`、`librsvg2-dev`、`patchelf` 后恢复通过。证据见
`vnext/eval/evidence/phase175-github-draft-pr-and-checks.json`。这解决的是交付校验环境问题，
不增加玩家评分，当前仍为 **95/100**；macOS/Windows 可见 GUI 与最终 cutover 门槛继续保持未闭合。

## Phase 176：PC Qwen3 创作兼容与世界实体一致性

在用户授权的 PC LM Studio（`huihui-ai_qwen3-14b-abliterated`）上完成真实 Probe 与隔离库 AI
世界起草：Probe 成功，学院题材草案返回 `valid=true`，地点、角色、NPC 和事件均来自请求题材。
针对本地模型常见的代码块/尾随解释、非标准 JSON 空白、中文误拼字段、字符串数值和角色重复为
NPC 的情况，增加了安全归一化；未知字段仍由严格 CreativeSource 校验阻止创建。桌面创建审阅、
确认页和世界详情现在展示“会在游玩中出现”的 NPC，避免正文引入未告知角色。后端全量
`144 passed`、Ruff、桌面测试/生产构建通过；macOS release 包已重建并在可见 GUI 中确认世界详情
显示 NPC。证据见 `vnext/eval/evidence/phase176-pc-qwen3-draft-compatibility.json`。

这是模型兼容性与信息透明度改进，尚未改变玩家总分（仍为 **95/100**）；Windows 安装后 GUI、
Android 真机和最终命名/切换门槛仍未通过，PR #2 保持 Draft。

## Phase 177：本机 Qwen 草案审阅一致性复测

在重建的 macOS release `DZMM.app` 中切回本机 `qwen2.5:7b`，Probe 5.4 秒成功，AI 世界草案
生成耗时 56.2 秒并进入确认前审阅。审阅页现在展示全部生成地点，并明确地点会进入可移动世界图；
角色卡人物仍会参与对话和主动事件，但额外 NPC 区不再重复列出角色卡。引用不存在地点时，后端
会在可容纳时把该地点加入素材，超过容量则阻止创建而不是静默指向其他地点。后端全量 `146 passed`、
Ruff、桌面 `36 passed` 和生产构建通过。证据见
`vnext/eval/evidence/phase177-local-qwen-draft-review-consistency.json`，代码提交为 `f10f69c`，当前文档头为 `99c8c22`。

本轮改善了草案可理解性和创建前一致性，但没有改变玩家总分（仍为 **95/100**）。Windows 安装后
GUI、Android 真机以及最终命名/切换仍是发布门槛；PR #2 继续保持 Draft。

## Phase 179：PC Qwen3 结构化草案复测

在重建的 macOS release `DZMM.app` 中将 `PC Qwen3 14B` 设为默认模型后，Probe 7.3 秒成功；
首次冷启动草案超时后，补充 LM Studio `json_schema` 结构化输出约束并重建，第二次草案在 20.7 秒
进入确认前审阅，状态为有效。草案生成 `潮汐回廊`、3 个地点、2 张角色卡和 2 个额外 NPC；越界的
数值字段被安全归一化，确认前没有写入世界或旅程。证据见
`vnext/eval/evidence/phase179-pc-qwen-structured-draft.json`。本轮提升了 PC 模型可用性，但玩家
总分暂保持 **95/100**，Windows 安装后 GUI 与完整 macOS 游玩旅程仍未验收。

## Phase 180：最新 PC 模型修复版跨平台产物

提交 `97f04cd` 上的 release workflow `33641453572` 已完成并全绿：macOS arm64 与 Windows x64
均通过后端测试、sidecar 构建、Tauri 打包、artifact smoke，以及 Windows 打包 sidecar 健康检查；
macOS DMG smoke 确认 `.app`、backend 和 `_internal` 均存在。该证据覆盖 LM Studio 结构化世界草案
约束修复，但仍不等同于 Windows 原生安装后的完整玩家 GUI 验收；评分保持 **95/100**。

## Phase 181：当前候选全量回归与 Android 设备边界

当前候选 `de1a2f8` 在本机完成后端全量 `146 passed`、Ruff、桌面 Vitest `36 passed`、桌面生产
构建和 Android Flutter `25 passed`。`adb devices` 当前没有在线设备，因此本轮只能确认 Android
代码/组件回归，不能新增真机安装或跨设备回读证据；Windows 原生安装后的 GUI 与 macOS 完整
可见玩家旅程仍保持未验收。评分继续保持 **95/100**。

## Phase 182：当前候选远端检查终态

文档更新后的当前候选 `55ac83f` 已通过 GitHub PR #2 的 `backend-ci` 和 `E2E smoke`；此前同一
代码候选 `97f04cd` 的 macOS arm64/Windows x64 release workflow 也已全绿。远端检查仅证明代码和
构建回归，不替代安装后玩家 GUI 旅程，因此评分保持 **95/100**，不提前执行 cutover。

## Phase 178：最新跨平台 release workflow

在提交 `da4e87d`（将数据库恢复演练改为隔离目录，避免 Windows SQLite 文件句柄锁定）上重新运行
release workflow `33526060462`。macOS arm64 与 Windows x64 均成功：后端测试、sidecar 构建、Tauri
打包、对应 artifact smoke 和打包 sidecar 健康检查均通过；macOS DMG smoke 确认 `.app`、backend
和 `_internal` 均存在。该结果证明发布产物链路已恢复跨平台绿灯，但仍不等同于 Windows 原生安装后的
完整玩家 GUI 验收，也没有改变玩家总分（仍为 **95/100**）。

## Phase 173：GitHub 分支与 PR 现状审计

只读核对 GitHub：仓库为公开仓库、默认分支为 `main`，当前没有 `feature/dzmm-vnext` PR；
远端 feature 分支仍停在 `6068dbb`，本地候选为 `1e92bd7`。因此当前候选还没有可引用的
远端 CI/PR 证据，必须在明确授权 push 后再创建。评分保持 **95/100**。

## Phase 167：macOS 安装包 GUI 门槛复核

重新检查当前 macOS 安装包：`dzmm-next-desktop` 进程存在，但 WindowServer 对该进程返回
可见窗口数为 0；同时旧版 `/Applications/dzmm.app` sidecar 仍在运行。按证据纪律，
进程/sidecar 健康不能替代玩家可见窗口，因此 macOS GUI gate 仍未通过，评分保持 **95/100**。
证据见 `vnext/eval/evidence/phase167-macos-gui-gate-recheck.json`。

## Phase 168：macOS Computer Use 权限复核

普通系统截图可以看到安装包窗口，但 `@oai/sky` 读取/操作应用时仍返回“Computer Use permissions
are not granted”。因此本轮没有执行或伪造任何 GUI 点击证据；macOS 安装包 gate 继续保持未通过。
证据见 `vnext/eval/evidence/phase168-macos-computer-use-permission-recheck.json`，评分保持 **95/100**。

## Phase 169：发布流水线新鲜度审计

最新成功 release workflow `33299415557` 的 head 为 `7a25ec8`，虽是当前分支祖先，但不包含
最近的 Android 模型端点/单行状态、桌面存储提示和运行时恢复测试改动。现有 Windows/macOS
产物只能作为历史 smoke 证据，必须从当前 cutover 候选重新运行 release workflow 后才能验收。
本轮不直接触发发布，评分保持 **95/100**。证据见 `vnext/eval/evidence/phase169-release-ci-freshness-audit.json`。

## Phase 171：远端候选新鲜度前置条件

核对发现远端 `origin/feature/dzmm-vnext` 仍在 `6068dbb`，本地候选已前进到 `5edf0dc`，
本地领先 12 个提交。远端 release workflow 无法验证这些未推送提交；按外部写入边界，
本轮不自行 push。证据见 `vnext/eval/evidence/phase171-remote-candidate-freshness.json`，
评分保持 **95/100**。

## Phase 170：当前候选本地打包复核

在当前候选上重新完成 sidecar PyInstaller 构建、桌面前端 `npm run build` 和
`desktop/src-tauri` 的 `cargo check`，均通过；仅先前一次命令因目录错误失败，修正后没有
代码错误。该证据只证明当前代码可构建，不替代远端 release workflow、Windows 原生安装或
macOS 完整可见旅程验收。评分保持 **95/100**。证据见
`vnext/eval/evidence/phase170-current-candidate-package-build.json`。

## Phase 164：旧版归档 tag 固定

已在旧版 `main@df38037` 上建立本地归档 tag
`dzmm-legacy-v0.16.0-2026-08-30`，作为 cutover 前的回滚锚点；未修改旧版提交内容，
也未将 vNext 合入 `main`。结构化证据见 `vnext/eval/evidence/phase164-legacy-archive-tag.json`。
恢复演练、桌面安装包 GUI gate 和最终命名收敛仍待完成，评分保持 **95/100**。

## Phase 165：旧版归档源码恢复演练

从 `dzmm-legacy-v0.16.0-2026-08-30` 创建隔离 detached worktree，确认恢复到
`df38037b6e3510d2e035e20600f49bd1f48ff077`、关键旧版源码存在且工作区干净，随后只删除
本轮创建的临时 worktree；当前 vNext、`main` 和归档 tag 均未改变。结构化证据见
`vnext/eval/evidence/phase165-legacy-restore-rehearsal.json`。这是源码回滚演练，运行时数据
恢复仍未声称完成，评分保持 **95/100**。

## Phase 147：macOS 包窗口与旧版端口共存复核

重新构建的 `DZMM.app` 已能在当前 GUI 会话捕获到可见 DZMM WebView 窗口，直接运行包内 sidecar
在隔离端口的 `/health` smoke 也通过。但本机旧版 `/Applications/dzmm.app` 的两个 sidecar
仍占用 `127.0.0.1:8765` 与通配端口，导致新包完整启动旅程不能作为通过证据。为降低过渡期冲突，
Tauri host 现在在未显式设置 `DZMM_NEXT_PORT` 时优先 8765、被占用则选择空闲 loopback 端口；
显式端口仍原样使用。该改动已 cargo check 通过，证据见
`vnext/eval/evidence/phase147-macos-window-and-port-collision.json`。

玩家评分保持 **93/100**：这是发布可靠性改进，不是新的可玩性分数。下一步需要在关闭旧版
sidecar 或全新用户目录的干净 GUI 会话重跑包内创建→游玩→结局→新 Run，随后再补 Windows
installer 和 Android release 证据。

## 当前玩家矩阵（实现后暂定）

| 玩家维度 | 满分 | 当前贡献 | 主要缺口 |
|---|---:|---:|---|
| 首次设置 | 15 | 12 | Windows/真实 provider 矩阵仍未验收 |
| World / Run 生命周期 | 15 | 15 | 本地模拟器已验证继续已有 Run、正式结束、返回 World 和同 World 新 Run；安装包重启和归档边界待验收 |
| 开场与沉浸游玩 | 30 | 28 | 共享 opening/对话/状态反馈、分层记忆、NPC 主动回应、Android/desktop 动态地点自由行动和同世界不同 Run 叙事差异已在模拟器/契约测试验证；30 回合、字体/TalkBack 待验收 |
| LLM 反馈和失败恢复 | 15 | 14 | 阶段、耗时、取消、零写入、重试、因果结果和缺少结构化选项的恢复已验证；安装包恢复和真实流式待验收 |
| 正式结局与重玩 | 15 | 14 | 正式结局、回顾、回 World、新 Run 已在本地模拟器验证；三端安装包待验收 |
| 三端一致性与安装证据 | 10 | 8 | macOS 包启动/Host 就绪、Windows NSIS/sidecar CI 和 Android 本地 release 模拟器已验证；Windows 安装后 GUI 和跨端旅程缺证据 |
| **玩家可玩性（暂定）** | **100** | **95** | **Android release 已完成新世界→10 回合→正式结局→同世界新 Run；Qwen 7B 单回合 35–90 秒，Android 真机、macOS/Windows 可见 GUI 和跨端回读仍缺证据，不能宣称发布完成** |

工程能力继续由测试、lint、构建、状态回读、portable 和打包证据单独记录，不与玩家分数平均。

## 当前代码质量矩阵

代码质量暂定 **85/100**：共享 Python command engine、story beat、model protocol、Experience Contract、LocalHostPort、
operation registry、operation stage boundary 和模型超时/连接恢复文案已形成可复用边界；Android 根页面已拆出模型、游玩、设置和
错误视图；desktop 已拆出模型档案 composable、共享 `ModelProfileEditor`、`ModelProfileList`、`PlayScene`、`OperationStatus`、`WorldRunLauncher`、active Run persistence、pending Run recovery、SSE parser、portable content 和跨 Run retry boundary，13 个组件/组合式/API/纯函数测试文件共 32 项通过；Android 游玩页和模型探测也已对齐准备/连接/生成/状态写入阶段，模型表单在本地调用前提供字段级校验；embedded model repository 已从
runtime 拆出；desktop 与 embedded runtime 现共用叙事提示、输出预算、技术摘要清洗和 provider 截断判定；embedded 模型 HTTP、JSON Schema 和安全 repair 也已独立，`core_runtime.py` 从 1288 行降到 1009 行；Android bridge 已收敛为单一 operation 集合，并由 contract test 校验 Dart/Kotlin 精确一致。主要扣分仍是约 1500 行的 `App.vue`、runtime 中剩余的 World/Run/Turn/portable 编排，以及三端 package E2E gate。详细评分和后续条件见
`docs/reviews/2026-08-21-cross-platform-player-code-scorecard.md`。

## 下一阶段门槛

1. M1：共享 `create_run`、World 详情、继续/新 Run、opening story beat 和结局后动作——已实现并完成桌面真实后端回归、Android 自动化覆盖。
2. M2：共享 operation state、阶段/耗时、取消、失败零写入、重试和对话/状态分层——已实现；桌面慢模型真实回归通过。
3. M3：ModelProfile CRUD/default/probe、引用冲突和三端一致交互——已实现；桌面真实回归、Android widget 覆盖通过。
4. M4：macOS/Windows 安装包和 Android 本地模拟器/真机完成 A-F、30 回合、重启/失败恢复——进行中；phase82–114 已累积补齐 Android 后台模型操作、三端玩家术语/操作阶段、正式结局、安全凭据、取消/恢复、归档世界、active Run 恢复、桌面 SSE、portable 内容边界、模型超时/连接恢复提示、模型 Probe 的连接/等待/耗时反馈、桌面模型列表边界、Android/desktop 动态地点和单地点自由行动 parity、跨 Run retry boundary 及 desktop notice live-region。phase149–151 已证明 macOS 包在旧版占用 8765 时可通过回退端口启动并显示 Host 就绪，phase150/153 已证明 Android API 36 release APK 可冷启动并在强制停止后恢复，phase152 已证明 Windows NSIS/sidecar 构建与 smoke 通过，phase157 已证明 Android release 新世界→10 回合→结局→同世界新 Run；当前精确缺口是 Windows 安装后 GUI、macOS 可见完整玩家旅程、Android 真机和跨端回读。
5. 所有玩家 P0/P1、分项和整体达到 85 后，才允许 `update_goal complete`。
## Phase 183：Android release 代码侧复核

在当前候选上重新执行 `flutter analyze` 与 `flutter build apk --release`，均通过；生成
`vnext/mobile/build/app/outputs/flutter-apk/app-release.apk`（93.7 MB）。构建输出提示
`file_picker`/`share_plus` 仍使用旧 Kotlin Gradle Plugin 接入方式，这是依赖升级事项，不影响
本次构建；由于 `adb devices` 为空，本轮不增加真机安装或玩家分数证据。
## Phase 184：Windows 安装后 Host 启动 smoke

在提交 `bde8022` 上运行 release workflow `33645485509`，Windows job 除了后端、sidecar 和 NSIS
内容检查外，新增静默安装到临时目录并启动安装后的 DZMM 主程序；程序继承临时数据目录和端口后，
`/health` 返回 `storage=local`、`host=127.0.0.1`，随后自动清理进程。macOS job 同样保持全绿。
这证明安装产物可启动本机 Host，但不替代 Windows WebView 的人工玩家旅程；评分保持 **95/100**。

## Phase 185：安装启动 smoke 的远端终态

包含新增安装启动步骤的当前 release workflow `33645485509` 已全绿：Windows 静默安装后的主程序
启动与 `/health` 检查通过，macOS arm64 同步通过构建与 DMG smoke；随后当前分支的 PR backend-ci
和 E2E smoke 也通过。自动化证据已闭合到“安装后 Host 可启动”，但 GUI 可见旅程和真实设备仍未
完成，评分保持 **95/100**。

## Phase 186：候选文档指针与 PR 检查终态

将交付文档中的候选版本指针刷新为 `feature/dzmm-vnext@0423101`。对应 Draft PR #2 的
`test` 与 `core-and-desktop` 检查均通过；本次仅为文档同步，不增加玩家分数。剩余门槛仍是
Windows/macOS 可见 GUI 旅程、Android 真机和跨端回读，未达到合并 `main` 或删除老版代码的条件。

## Phase 187：Mac 本地 Qwen 7B 新世界首回合

在隔离临时数据目录中使用 Ollama 本机 `huihui_ai/qwen2.5-abliterate:7b`，完成
“AI 草案→确认创建世界→创建 Run→选择首个故事选项”的真实闭环。草案有效，世界为
`星辰的低语`，主角为 `艾莉娅·斯通`，选择 `援手图南` 后回合提交到 revision 1；
叙事未被截断，且正文从所选角色开始承接。证据见
`vnext/eval/evidence/phase187-mac-local-qwen-choice.json`。本轮只增加本地模型兼容性证据，
玩家分数保持 **95/100**；安装包可见 GUI、Android 真机和跨设备回读仍未闭合。

## Phase 188：Mac 本地 Qwen 7B 十回合与沉浸过滤

在隔离临时 Host 中使用同一 Mac 本地 7B 完成 10 回合并到达 `lan-dawn` 正式结局，
平均回合约 32.8 秒，未发生 provider 截断。回合 6–10 暴露模型偶发输出
`choice_id`/`chapter_id`/LaTeX 等自检文本；已在 `d1a4adc` 增加通用叙事清理与回归测试，
避免将这类内容直接展示给玩家。该修复尚需新进程回合确认，评分保持 **95/100**；三端安装包
GUI、Android 真机和跨设备回读仍是替换门槛。证据见
`vnext/eval/evidence/phase188-mac-local-qwen-10-turn.json`。

## Phase 189：Mac 本地 Qwen 7B 过滤后路线矩阵

在最新叙事清理规则提交 `df84a53` 上，继续使用 Mac 本机 Ollama
`huihui_ai/qwen2.5-abliterate:7b`，以全新临时数据目录跑通 5 条 Fog Harbor 路线、共 15 个
真实选择回合。每条路线均产生非空正文并到达预期结局；随后回滚首回合并重新读取，均恢复到
第二章且结局重新解锁。回合耗时 10.2–24.3 秒，中位数 15.6 秒。新增的“根据语境/答案是/角色
列表/在转述中”等自检段落清理规则由单测与该真实矩阵共同覆盖。该轮仍未完成安装包可见 GUI、
Android 真机和跨设备回读，玩家评分保持 **95/100**。
证据见 `vnext/eval/evidence/phase189-mac-local-qwen-filtered-matrix.json`。

## Phase 190：当前候选 Android release 构建

在候选提交 `cd7428d` 上重新执行 Android `flutter analyze`、25 项 widget 测试和
`flutter build apk --release`，全部通过。生成 APK 为 93.7 MB，SHA-256 为
`47ad73b349f504644d958310937d4b9cb4cb0c4acc3242a2a84ce9ce9a2781e0`。本轮没有连接模拟器，
因此不把构建证据扩大解释为安装或玩家旅程验收；评分保持 **95/100**。证据见
`vnext/eval/evidence/phase190-current-android-release-build.json`。

## Phase 191：当前候选 macOS 安装包 Host smoke

从当前候选重新构建 arm64 PyInstaller sidecar 与 Tauri `DZMM.app`，在临时数据目录和端口
`18773` 冷启动包内二进制；`/health` 返回 `app=dzmm-next`、`api_version=2`、
`storage=local`、`host=127.0.0.1`、`foreign_keys=true`。由于 Mac 仍处于锁屏，本轮只记录
当前安装包 Host 启动，不扩大解释为可见 GUI 玩家旅程，评分保持 **95/100**。证据见
`vnext/eval/evidence/phase191-current-macos-package-health.json`。

## Phase 192：发布候选冻结与产物指纹

冻结候选代码 `feature/dzmm-vnext@af0fc4012bdb32ba7880273b912c23e7babb701e`（后续仅有证据文档提交）；PR #2 的
`test` 与 `core-and-desktop` 均为 success，合并状态为 `CLEAN`。当前 Android release APK
SHA-256 为 `47ad73b349f504644d958310937d4b9cb4cb0c4acc3242a2a84ce9ce9a2781e0`，当前
macOS arm64 DMG SHA-256 为 `735201e3e2d0ed151b09d2ee3c8a8edcabe2073bba9c88dcb40aa6039747d917`。
本机当前没有连接 Android 设备或 AVD，因此本阶段只冻结候选身份和产物完整性，不宣称 GUI/模拟器
验收，评分保持 **95/100**。证据见 `vnext/eval/evidence/phase192-release-candidate-freeze.json`。

## Phase 193：macOS 当前候选可见 GUI 创建、游玩与新 Run 回放

从 `feature/dzmm-vnext@90d9236` 重建当前 arm64 `DZMM.app`/DMG，并用精确 bundle 路径打开，避免误用
旧版 `/Applications/dzmm.app`。Mac 本地 `ollama/qwen2.5:7b` 完成 AI 草案审阅、确认创建新世界、进入
开场、执行首个选择并看到 `preparing/connecting/generating/applying` 阶段；回合保存了新章节、线索、
关系变化和 NPC 主动联系。返回世界列表后，刚创建的世界显示世界书 2 条、角色卡 2 张、NPC 4 位，
并成功展开“开始新旅程”创建独立第二局，新的主角和开场均可见。

本轮还确认题材中立修复已进入当前产物：长回合桥接选项为“暂缓行动，等待更佳时机”，草案中没有
`雾港`/`潮门`/`雾灯`模板词。但首回合正文仍出现“回到港口”等地点连续性和 NPC 插入不自然问题；
本轮未完成 10 章可见结局及结局后新 Run 回放，因此 macOS gate 记为 partial pass，玩家评分保持
**95/100**。证据见 `vnext/eval/evidence/phase193-macos-packaged-visible-gui.json`。
