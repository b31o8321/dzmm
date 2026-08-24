# DZMM vNext Active Delivery Index

更新时间：2026-08-21
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

完成门槛：所有 P0 维度及整体成熟度均 >=85；正式代码、UI、测试、配置、依赖、迁移和发布产物中不再存在废弃的 remote/LAN/mDNS/QR/pairing/scope 能力。

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

## 当前玩家矩阵（实现后暂定）

| 玩家维度 | 满分 | 当前贡献 | 主要缺口 |
|---|---:|---:|---|
| 首次设置 | 15 | 12 | Windows/真实 provider 矩阵仍未验收 |
| World / Run 生命周期 | 15 | 15 | 本地模拟器已验证继续已有 Run、正式结束、返回 World 和同 World 新 Run；安装包重启和归档边界待验收 |
| 开场与沉浸游玩 | 30 | 28 | 共享 opening/对话/状态反馈、分层记忆、NPC 主动回应、Android/desktop 动态地点自由行动和同世界不同 Run 叙事差异已在模拟器/契约测试验证；30 回合、字体/TalkBack 待验收 |
| LLM 反馈和失败恢复 | 15 | 14 | 阶段、耗时、取消、零写入、重试、因果结果和缺少结构化选项的恢复已验证；安装包恢复和真实流式待验收 |
| 正式结局与重玩 | 15 | 14 | 正式结局、回顾、回 World、新 Run 已在本地模拟器验证；三端安装包待验收 |
| 三端一致性与安装证据 | 10 | 7 | macOS 包和 Android 本地模拟器已验证；Windows 包和跨端旅程缺证据 |
| **玩家可玩性（暂定）** | **100** | **90** | **仍有发布阻断，不能宣称完成；新世界 Qwen 长局一致性仍待人工复测** |

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
4. M4：macOS/Windows 安装包和 Android 真机完成 A-F、30 回合、重启/失败恢复——进行中；phase82–114 已累积补齐 Android 后台模型操作、三端玩家术语/操作阶段、正式结局、安全凭据、取消/恢复、归档世界、active Run 恢复、桌面 SSE、portable 内容边界、模型超时/连接恢复提示、模型 Probe 的连接/等待/耗时反馈、桌面模型列表边界、Android/desktop 动态地点和单地点自由行动 parity、跨 Run retry boundary 及 desktop notice live-region。phase106–107 证明当前 macOS 26.3.1 观察会话无法提供可见 WebView 窗口，且控制应用也无法枚举窗口；当前精确阻塞为 macOS GUI 观察条件、Windows 原生构建环境和空的 `adb devices`。
5. 所有玩家 P0/P1、分项和整体达到 85 后，才允许 `update_goal complete`。
