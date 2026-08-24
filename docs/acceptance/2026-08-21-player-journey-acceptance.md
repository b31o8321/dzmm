# DZMM vNext 玩家旅程验收清单

日期：2026-08-21  
状态：Implementation pass / package-device gates blocked  
适用平台：macOS、Windows、Android

## 证据规则

- 使用安装产物和隔离测试数据；不得写入或删除真实 `~/.dzmm` 与 Android 正式应用数据。
- 每个平台保存构建标识、设备/系统、模型档案、起止时间、截图或录屏、日志和 SQLite 回读结果。
- API、单测、构建、模拟器脚本只作为辅助证据；不能替代玩家入口的 UI 验收。
- 每个操作记录 `pass / fail / blocked / not-run`，失败必须保留复现步骤。

## 2026-08-21 实现回归快照

以下项目已在当前脏工作树完成实现并有自动化或桌面真实后端证据：

- `pass`：World 继续/同世界新 Run、开场场景/角色/对话/目标、回合叙事和状态反馈；Android 与桌面均支持可恢复的 World 归档/恢复，归档期间禁止新 Run 和推进。
- `pass`：准备/生成/写入/完成阶段、耗时、慢模型取消、失败重试；取消不会增加 revision 或 turn_count。
- `pass`：模型编辑、删除、设默认、默认标记和引用冲突提示；首次启动直接展开中性模型配置，不含开发者私网默认值；Ollama/LM Studio/OpenAI-compatible 的协议与 Base URL 预设在桌面和 Android 一致；认证模型 API Key 分别进入桌面系统密钥链或 Android 安全存储，SQLite/导出包不保存明文；Android widget 覆盖相同控制。
- `pass`：正式结局标题/叙事、最终路线、持有物品、人物关系、最近三次关键行动和回合数摘要，以及回到 World、同一 World 新 Run；Android widget 覆盖相同结束态。
- `pass`：后端 112 tests + Ruff、桌面 28 tests/生产构建、Flutter 20 tests/analyze、debug APK 构建、macOS arm64 app/DMG 产物；Android 游玩、模型 Probe 和 AI 起草均有共享阶段/耗时/取消组件覆盖，模型生成/校验/Probe 已移出 Android UI 线程；桌面与 Android 现共用叙事提示、输出预算、技术摘要清洗、截断判定和模型超时/连接恢复文案，Probe 在 10 秒、叙事/草案在 120 秒边界后明确说明未写入结果与重试/换模型动作；同一真实 Ollama 模型的普通回合与正式结局均已完整输出；桌面自由行动和故事选择现消费 local-host SSE 叙事增量，只有状态提交完成后才刷新 Run；portable 内容合并已从页面编排器提取为纯函数边界；World 归档/恢复已在共享 Android bridge 实运行，归档世界的既有旅程保持查看但不可继续；choice 与自由行动入口仅在各自有效时显示；玩家主界面不再展示 revision、内部 Run/WorldVersion ID 或资源 ID；回滚记录已从正式回合数/关键行动中排除；AI 草案取消后不会创建 World、旅程或存档，取消传输失败时仍能恢复；桌面和 Android 重开时会解释未完成 Run 操作没有写入半个回合；release workflow 已锁定 PyInstaller package extra；桌面已有跳过导航、可见焦点、reduced motion、离线字体和 live announcement 防回退，Android 新旅程弹窗不再强制唤起键盘；当前 macOS 包已清除退役迁移缓存，并验证正常退出与父进程异常终止后 sidecar 都会同步关闭。

仍为 `blocked` / `not-run`：Windows 安装包真实旅程、Android 物理设备 A-F 旅程、三端安装包 30 回合与
重启恢复。当前 macOS 26.3.1 的 DMG 另已判定 `fail`：Host 正常但 WindowServer 中没有玩家可见窗口。机器证据记录在 `vnext/eval/evidence/phase72-player-first-implementation.json`、
`vnext/eval/evidence/phase78-operation-stage-contract-parity.json` 和
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
`vnext/eval/evidence/phase91-player-surface-technical-leakage.json`、
`vnext/eval/evidence/phase92-formal-ending-recap-parity.json`、
`vnext/eval/evidence/phase93-player-language-parity.json`、
`vnext/eval/evidence/phase94-offline-keyboard-accessibility-boundary.json`、
`vnext/eval/evidence/phase95-model-first-run-provider-parity.json`、`vnext/eval/evidence/phase96-rollback-and-credential-boundary.json`、
`vnext/eval/evidence/phase97-draft-cancellation-boundary.json`、`vnext/eval/evidence/phase98-cancellation-transport-recovery.json`、
`vnext/eval/evidence/phase99-release-sidecar-dependency-gate.json`、`vnext/eval/evidence/phase100-archived-world-view-only-boundary.json`、
`vnext/eval/evidence/phase101-interrupted-run-recovery-marker.json`、`vnext/eval/evidence/phase102-imported-run-recovery.json`、`vnext/eval/evidence/phase103-desktop-narrative-stream.json`、`vnext/eval/evidence/phase104-portable-content-boundary.json`、`vnext/eval/evidence/phase105-player-model-timeout-feedback.json`、`vnext/eval/evidence/phase106-macos-packaged-webview-window-gate.json`、`vnext/eval/evidence/phase107-macos-window-control-experiment.json`。
`vnext/eval/evidence/phase101-interrupted-run-recovery-marker.json`、`vnext/eval/evidence/phase102-imported-run-recovery.json`、`vnext/eval/evidence/phase103-desktop-narrative-stream.json`、`vnext/eval/evidence/phase104-portable-content-boundary.json`、`vnext/eval/evidence/phase105-player-model-timeout-feedback.json`、`vnext/eval/evidence/phase106-macos-packaged-webview-window-gate.json`、`vnext/eval/evidence/phase107-macos-window-control-experiment.json`、`vnext/eval/evidence/phase108-model-probe-loading-parity.json`、`vnext/eval/evidence/phase109-desktop-model-list-boundary.json`、`vnext/eval/evidence/phase110-android-free-action-destination-parity.json`、`vnext/eval/evidence/phase111-destination-presentation-parity.json`、`vnext/eval/evidence/phase112-single-location-action-parity.json`。
`vnext/eval/evidence/phase113-retry-run-boundary.json`。
`vnext/eval/evidence/phase114-desktop-notice-live-region.json`。
`vnext/eval/evidence/phase115-android-operation-live-region.json`。
`vnext/eval/evidence/phase116-latest-package-artifacts.json`。
`vnext/eval/evidence/phase117-android-emulator-qwen7b-session.json`。

phase107 进一步验证了当前观察会话的边界：Tauri 2.11.5 / tao 0.35.3 / wry 0.55.1 隔离构建仍为 0 个窗口；旧版 `dzmm.app` 与 Calculator 控制应用在同一会话也为 0 个窗口。因此当前 macOS gate 继续算 `fail`，但不能据此认定是 DZMM 生命周期代码；需要在已知控制应用可见的正常 GUI 会话中重跑 A-F。

## 共同体验指标

| 指标 | 门槛 |
| --- | --- |
| 首次模型配置 | 不含安装/下载，3 分钟内完成保存、Probe、设默认 |
| 操作反馈 | 点击后 200ms 内出现可见反馈，不允许静默禁用 |
| 慢模型解释 | 8 秒后仍生成时显示耗时、阶段、取消和恢复说明 |
| 首次开局 | 进入 Run 后先见开场叙事，再出现可行动入口 |
| 数据安全 | 失败/取消不增加 revision/turn_count，不产生半成品 Turn |
| 恢复 | force-stop/reopen 后已完成状态一致，未完成操作有明确说明 |
| 一致性 | 三端 P0 动作、结果和错误恢复一致 |

## A. 首次设置

- [ ] 空模型状态解释为什么需要模型，并提供唯一主动作“添加模型”。
- [ ] 创建 Ollama、LM Studio/OpenAI-compatible 档案。
- [ ] Base URL、模型名和凭据校验落在具体字段。
- [ ] Probe 显示连接中、成功、网络失败、HTTP error body、空内容、超时。
- [ ] 编辑档案后新配置生效，旧密钥不会意外回显或丢失。
- [ ] 设置默认模型；重启后仍为默认。
- [ ] 删除未引用模型成功。
- [ ] 删除默认或被 Run 引用模型时获得可执行提示。

## B. World 与 Run

- [ ] 世界列表显示内容摘要、Run 数、最近游玩和状态。
- [ ] 点击世界进入可操作详情；不得存在空 tap/click handler。
- [ ] 有运行中 Run 时，“继续上次 Run”进入正确 revision。
- [ ] “开始新 Run”允许确认 Hero、模型和开场偏好。
- [ ] 新 Run 使用新 ID，不修改已有 Run。
- [ ] 没有 Run 的 World 仍可开始。
- [ ] 归档 World 后不能新开或推进 Run；恢复后可继续。

## C. 开场与沉浸游玩

- [ ] 新 Run 首屏有场景、处境、角色/线索和行动引导。
- [ ] 旁白、角色对话、玩家行动和状态结果视觉层级可辨。
- [ ] choice 规则只显示有效 choice；自由行动可用时才显示输入框。
- [ ] 玩家选择后立即出现“正在处理”状态。
- [ ] 生成内容逐步出现，或在不支持流式时持续显示阶段和心跳。
- [ ] 回合完成后出现新的叙事、对话/反馈和下一步入口。
- [ ] 默认视图不以 revision、schema、Python 裁判等技术词为主标题。
- [ ] 文字缩放、大字体、键盘焦点和 TalkBack 顺序可用。

## D. 失败、取消与恢复

- [ ] 模型不可达：说明未写入状态，并提供重试/换模型。
- [ ] HTTP 200 error body：不得当作成功或空叙事提交。
- [ ] 空输出：不生成空 Turn。
- [ ] 超时：显示耗时、取消和继续等待。
- [ ] 取消：回到原 revision，输入/选择仍可恢复。
- [ ] 应用在 generating/applying 阶段被结束：重开后状态可解释且一致。
- [ ] revision conflict：刷新最新 Run，再允许重新行动。

## E. 正式结局与重玩

- [ ] 最终选择由 Python 计算并锁定 ending。
- [ ] 结局页显示标题和完整叙事，不直接显示内部 `narrative_key`。
- [ ] 显示关键选择、关系/路线摘要和回合数。
- [ ] 结束后不可继续写当前 Run。
- [ ] “回到世界”可查看本局。
- [ ] “开始新 Run”创建独立初始状态。
- [ ] “回滚”恢复到允许的历史点并清除锁定结局。

## F. 持久化与跨端一致性

- [ ] macOS 安装包完整通过 A-E。
- [ ] Windows 安装包完整通过 A-E。
- [ ] Android 真机完整通过 A-E。
- [ ] 每端完成 30 回合、三次重启恢复和一次失败/取消恢复。
- [ ] portable Run 在两个平台间往返后使用新 ID，叙事/状态/结局一致。
- [ ] 三端功能矩阵无 P0/P1 缺口。

## Phase 118：Android 游玩界面和剧情变化边界

- [x] 主滚动区只承载历史；最新场景、加载阶段和当前操作入口在底部。
- [x] 常驻状态可收起；状态反馈、重大事件和行动回合进入独立记录模块。
- [x] 新 Run 模拟器人工检查到开场叙事和底部 choice；未清理既有世界/模型档案。
- [x] 已确认剧情规则是固定章节图，模型只生成正文；相同选择序列会复现结构与结局。
- [x] per-Run 变化（Run seed/场景变体/变化提示）已在 phase119 实现；qwen 7B 双 Run 的人工差异验收仍待完成。

证据：`vnext/eval/evidence/phase118-mobile-play-surface-and-plot-boundary.json`。

## Phase 119：老版 GM 回合边界与每 Run 叙事变化

- [x] 参考老版 DZMM：LLM 负责 GM 场景、NPC、线索和意外后果；Python 继续负责骰子、资源、关系、章节、路线、数值和结局硬校验。
- [x] 章节世界的预设选项改为建议；`narrate`/`move` 自由行动可直接推进，不再被 choice planner 拦截。
- [x] 状态保存最近 6 回合的玩家输入、叙事和机械结果，下一回合重新注入 GM 记忆。
- [x] Run ID 作为独立变化种子；每回合注入新的环境/NPC/线索压力点，模型采样温度设为 0.85、top-p 设为 0.9。
- [x] 后端全量 113 项测试、Ruff 通过；新增自由行动和 `narrative_context` 持久化测试。
- [ ] 尚未完成 qwen 7B 双 Run 人工对照；必须确认同世界重开后的钩子、NPC 反应和叙事路径有差异，并确认硬状态无越权。

证据：`vnext/eval/evidence/phase119-emergent-gm-narrative-contract.json`。

## Phase 120：地点/NPC/世界事件运行时概念迁移

- [x] RunState 持久化地点访问、NPC 动态状态、活跃世界事件、剧情线容器和待回应互动。
- [x] NPC 被叙事提及或发言后记录为已遇见；Python 按当前位置、相遇状态、主动性和冷却回合调度 NPC 主动联系。
- [x] 预定义世界事件支持 `initial_active` 或 `trigger_turn`，激活结果进入状态反馈和下一回合 GM 上下文。
- [x] StoryBeat、desktop 和 Android 支持多段结构化 NPC 对话；主动事件会改变下一步行动引导。
- [x] 后端 116 项测试/Ruff、desktop 32 项/构建、Flutter 22 项/analyze 通过；最新 APK 已安装模拟器。
- [ ] LLM 结构化 `gm_actions` 尚未开放给模型自由创建/解决剧情线和隐藏事件，需下一阶段加 Python allowlist、去重和回滚测试。

证据：`vnext/eval/evidence/phase120-world-runtime-npc-initiative.json`。

## Phase 121：受限 GM actions 与世界动态演化

- [x] 模型可以通过不可见尾部标记提出新剧情线、隐藏事件及其解决意图；玩家只看到清洗后的正文。
- [x] Python 只接受固定 action 类型、合法 ID、长度/枚举/目标检查，并对重复动作去重。
- [x] 关系、数值、背包、章节、路线和结局仍不能由模型直接写入；非法动作不会造成部分状态提交。
- [x] desktop 非流式、SSE 流式和 embedded Android 回合链路都接入相同的状态应用边界；旧 narrator seam 保持兼容。
- [x] 后端全量 117 项测试、Ruff、desktop 32 项/构建、Flutter 22 项/analyze 通过；Android debug APK 已重新构建。
- [ ] 当前 `adb devices` 为空，APK 尚未安装到模拟器/真机；安装验证待设备上线。

证据：`vnext/eval/evidence/phase121-gm-actions-allowlist.json`。

## Phase 122：AI 世界素材与老 DZMM 运行时概念对齐

- [x] AI 世界草案可安全携带 NPC、势力、世界事件和地点连接等描述性素材。
- [x] Python 为动态实体分配 ID，限制数量/长度/枚举，并把地点引用解析为现有地点 ID。
- [x] 角色卡同步为运行时 NPC；NPC 具备地点、动机和主动联系冷却字段。
- [x] embedded 草案的安全回退保留描述性 NPC/事件/势力，而不是只保留静态章节骨架。
- [x] 后端全量 119 项测试、Ruff 通过；Android debug APK 已重新构建。
- [ ] 当前 `adb devices` 为空，APK 尚未安装到模拟器/真机。

证据：`vnext/eval/evidence/phase122-ai-world-runtime-material.json`。

## Phase 123：结构化世界事件谓词与势力张力

- [x] 事件支持地点到达、NPC 状态、物品拥有、旗标、势力张力以及 `all/any` 组合条件。
- [x] 势力状态进入 RunState，包含张力、每回合增长、冲突阈值和最后推进回合。
- [x] 每个 revision 只推进一次势力张力；事件条件不满足时不会激活，未知/畸形谓词安全返回 false。
- [x] 事件状态变化仍由 Python 完成，模型只能读取上下文并提出叙事或受限 `gm_actions`。
- [x] 后端全量 120 项测试、Ruff 通过；Android debug APK 已重新构建。
- [ ] 当前 `adb devices` 为空，APK 尚未安装到模拟器/真机。

证据：`vnext/eval/evidence/phase123-runtime-event-predicates.json`。

## Phase 124：事件完成与 Campaign / Phase 推进

- [x] 世界事件支持 Python 可验证的 `completion_conditions`，满足后进入 `resolved`。
- [x] Campaign 状态记录当前阶段、已完成事件和已完成阶段。
- [x] 当前阶段关键事件达到 `required_count` 后，Python 推进到下一阶段；同一事件不会重复计入。
- [x] Campaign/事件状态注入桌面与 embedded GM 上下文，模型不直接写入进度。
- [x] NPC 运行时状态支持所属势力与初始声誉，并注入后续回合上下文。
- [x] 后端全量 121 项测试、Ruff 通过。
- [x] 本地 `dzmm-ux-api36` Android 36 模拟器已启动，APK 已安装并打开主 Activity。

证据：`vnext/eval/evidence/phase124-campaign-event-completion-emulator.json`。

## Phase 125：本地 Qwen 7B 玩家旅程与缺少选项恢复

- [x] 本地 `dzmm-ux-api36` 模拟器通过 `adb reverse` 接入本机 `qwen2.5:7b`。
- [x] 连续 3 回合观察到 preparing / connecting / generating / applying Loading 阶段。
- [x] 模型返回正文但缺少结构化 `available_choices` 时，Android 进入安全的自由行动分支，不再让页面停在旧内容。
- [x] 正式结局摘要、关键行动和同一 World 新 Run 已在模拟器验证。
- [x] 新 Run 重新显示开场叙事和选项；Flutter 24 项测试、analyze、APK 构建通过。
- [x] 相同世界、相同首个选择的两个 Run 产生不同叙事，并出现 NPC 主动事件；本地模拟器验收评分由 78 提升至 85。
- [ ] 若后续一轮不再明显提升，则停止 Goal。

证据：`vnext/eval/evidence/phase125-local-emulator-qwen7b-player-journey.json`。

## Phase 126：从零创建新世界与 NPC/事件对话验收

- [x] 不复用既有世界，从 Android AI 世界向导创建了全新“潮汐之门”世界。
- [x] Qwen 7B 紧凑草案保留 2 个角色、2 个地点、4 个运行时 NPC、2 个势力和 2 个事件；Python 仍接管章节、选项、关系、路线和结局等硬规则。
- [x] 新世界开场使用生成地点“月光港”、角色“艾莉/杰克”和重写后的建议“援手艾莉 / 替杰克保守秘密”，不再显示旧模板“救岚 / 沈砚”。
- [x] 首个选择后，Qwen 正文引用“月光港、艾莉、老渔夫汤姆”和小巷线索，并触发“艾莉主动找到了你”的待回应互动；下一步建议同步使用生成角色名。
- [x] 修复 compact story、直接描述性 NPC 素材和主角与首角色同名时的开场对话边界；后端 124 项测试、Ruff、Flutter 24 项/analyze、APK 构建均通过。
- [x] 本轮玩家评分由 85 提升至 86；若下一轮不再有明显分值提升，停止 Goal。

证据：`vnext/eval/evidence/phase126-new-world-qwen7b-quality.json`。

## Phase 127：Android 草案审阅与叙事上下文收口

- [x] AI 世界确认前新增“生成素材摘要”，展示地点、角色/NPC、势力和事件，并明确模型素材与本机 hybrid 规则的边界；widget test 验证摘要内容和确认前零写入。
- [x] 不复用旧存档，从 Android 向导创建全新“潮汐之门”世界，保留风暴之眼/月光港、艾莉森/墨菲斯托、老船长/海妖莉娅、守护者联盟/暗影海盗团及风暴突袭/潮门重开素材。
- [x] 本地 Qwen 7B 完成 3 回合，选择“援手艾莉森 / 把证词交给艾莉森 / 点亮雾灯”，正式结局持久化，回到 World 后可开始同世界新 Run。
- [x] 叙事请求改用玩家可见实体名、章节/结局显示标签和禁止内部 ID/旧模板名的 guardrail；复测正文引用生成 NPC 并触发老船长主动联系，不再出现内部 `lan` 被写成旧名“兰”。
- [x] 后端 127 项测试、Ruff、Flutter 23 项/analyze、APK 构建通过；最新 APK SHA-256 为 `e84207e9592fc90bf1d30008d50d5a97ea50c364a542c4b788de4d5270e8063b`。
- [x] 玩家评分由 86 提升至 87（+1）。由于剩余事项主要是 Windows/macOS/Android 发布环境和真机验收门槛，本 Goal 按退出机制停止。

证据：`vnext/eval/evidence/phase127-next-goal-draft-review-and-context-grounding.json`。

## Phase 128：玩家反馈整组修复与移动端阅读层

- [x] Android 世界详情提供永久删除入口；二次确认明确说明世界、旅程、回合和历史会一并删除，后端删除路径已覆盖级联记录。
- [x] 操作阶段和耗时保持单行展示；阶段过多时可横向查看，不再换行挤压内容。
- [x] 草案审阅改为玩家可理解的“可创建/暂不能创建”结论和素材摘要；不可玩草案不会进入创建流程，技术修复路径不再直接展示。
- [x] 安全世界映射不再把雾港 lorebook、雾灯和旧章节文本带入模型生成世界；离线模板明确标注为固定雾港示例。
- [x] Android 游玩历史、当前新内容和选项拆分为独立阅读区域；长当前正文先显示摘要，可打开全文。
- [x] 后端 129 项测试、Ruff、Flutter 24 项/analyze、桌面 32 项/构建通过；APK 已安装至 `emulator-5554`，SHA-256 为 `cff89639321830fd338072fec48e33fd42ad50689226a0edadb32fc19ca338b1`；模拟器截图已同时看到长文摘要和底部选项。
- [x] 模拟器验证模型起草的单行等待/超时反馈和离线模板审阅；Qwen 7B 本轮 120 秒无响应，因此不把新世界叙事质量标记为人工通过。
- [ ] 用户用响应的本机 Qwen 配置从创建新世界开始，验收素材一致性、对话/选项因果关系、历史滚动和删除二次确认。

证据：`vnext/eval/evidence/phase128-player-feedback-world-integrity-and-mobile-reading.json`。

## Phase 129：玩家体验 Goal 评分推进

- [x] 第一轮：当前回合先显示主要状态结果，其他变化可展开；模拟器中选择后仍能看到下一步选项和 Loading 阶段，玩家评分 87→88。
- [x] 第二轮：分层记忆注入最近行动、未完成剧情线、活动事件和触发世界书；Android“当前状态”可展开查看地点、路线、物品、人物关系和线索，玩家评分 88→89。
- [x] 第三轮：NPC 主动联系的当前故事卡保留“正在等待回应”和回应提示，不因紧凑布局而隐藏行动原因，玩家评分 89→90。
- [x] 后端全量 132 项测试、Ruff、Flutter 24 项/analyze、APK 构建通过；APK SHA-256 为 `e3f1b3b679e3a88f2c5e947bb720ac963c42f059436c76e5693b50e5fc8742ad`，已安装至 `emulator-5554`。
- [ ] 新世界使用响应的本机 Qwen 完成长局人工验收；若连续两轮玩家评分没有明显提升，按 Goal 退出机制停止继续改动。

证据：`vnext/eval/evidence/phase129-player-experience-goal.json`。

## 评分规则

以下六项分别评分；任何一项 P0 未通过时，总可玩性封顶 30 分：

1. 首次设置 15 分；
2. World/Run 生命周期 15 分；
3. 开场与沉浸游玩 30 分；
4. LLM 反馈和失败恢复 15 分；
5. 结局与重玩 15 分；
6. 三端一致性和安装证据 10 分。

发布门槛：每项至少 85%，总分至少 85/100，且无 P0/P1 未通过。
