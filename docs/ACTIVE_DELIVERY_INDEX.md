# Active Delivery Index

## DZMM vNext 干净重做

- **状态：** Active — Phase 0–3 的已实现范围已有中间证据；当前进入打包桌面壳、模型流失败恢复与长局验收。叙事规则集已进入产品/架构评审，批准后以“剧情冒险 + 关系 + 多结局”垂直切片推进，再进入 Android/LAN RC。
- **日期：** 2026-08-16
- **工作树 / 分支：** `.worktrees/dzmm-vnext` / `feature/dzmm-vnext`
- **基线：** `main` at `df38037` (`v0.16.0`)
- **目标：** 在隔离的 vNext 产品根中重建 DZMM：单一版本化世界聚合、可恢复 Python-first 回合、受限 Lorebook/内容导入、Mac host 与 Android gameplay client。旧数据库、旧 API 和旧代码不构成迁移或兼容约束。

### Canonical artifacts

- [产品与领域现状评审](reviews/2026-08-16-dzmm-product-domain-review.md)（历史与设计参考）
- [ADR-002：vNext 干净重做](adr/ADR-002-vnext-clean-slate-rebuild.md)
- [vNext 规格、评分矩阵与分阶段实施计划](superpowers/specs/2026-08-16-dzmm-vnext-clean-rebuild.md)
- [叙事规则集：互动叙事平台规格、雾港示例、矩阵与 Plan](superpowers/specs/2026-08-17-narrative-rulesets-interactive-story-platform.md)
- [ADR-003：在版本化世界聚合上扩展叙事规则集](adr/ADR-003-narrative-rulesets-on-versioned-world-aggregate.md)
- [ADR-004：世界书与角色卡的互通内容边界](adr/ADR-004-interoperable-lorebook-and-character-card-boundary.md)
- [世界中心交互原型](prototypes/2026-08-16-world-center-prototype.html)

### 已确认决策

1. DZMM vNext 定位为「本地优先、状态驱动的互动叙事平台」；TRPG、剧情冒险、关系叙事和受限 hybrid 共享一个版本化聚合，Python 决定规则与状态，不复刻酒馆的完整提示词/脚本工作台。
2. vNext 不迁移真实用户数据，不兼容旧 API、旧 schema 或旧页面；`main` 只作为产品行为和测试设计的参考。
3. 世界是一个版本化 aggregate；世界书（Lorebook / World Info）是受限叙事知识层，不能直接写入运行态。
4. Android 仍为 gameplay-only client，Mac 为 host；vNext 使用版本化的独立 API，而不是兼容旧远程接口。
5. 每阶段只能按 vNext 成熟度矩阵累积证据；旧项目的 88.1 成熟度和 Android CI 不能转移为 vNext 分数。
6. 世界书（Lorebook / World Info）与角色卡（Character Card）采用生态通用概念和安全互通；它们是内容/上下文层，不能直接写 RunState。`WorldDefinition` 仅为内部契约术语。
7. 世界书与角色卡不只是兼容导入格式，而是 vNext 的一级、可版本化内容资产。公开 API、UI 与存储 contract 固定采用 `lorebook` / `character_cards`；当前 `lore` 和“角色卡转建议主角”的实现仅为未完成的过渡状态，不能作为 Phase 2 完成证据。
8. 角色卡是可移植内容，不承载本世界的关系数值或结局规则；schema v3 的规则集通过显式 `RelationshipDefinition → character_card_id` 引用角色卡，relationship event 只引用 relationship ID。v2 卡内 `relationship_dimensions` 被拒绝；schema v3 数据目录独立于早期 preview，且不迁移或打开 v2 World/Run。

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
- **Mobile control-plane 基础（未计分）：** `4ccd8c9` 增加 API v2 独立配对请求、loopback host 批准、一次性 token 交付、token 哈希校验与撤销；mobile bearer 只能读 Run 和提交 gameplay SSE，不能触及世界/模型管理。28 项后端测试覆盖批准、使用、撤销和流式回合。尚无 Flutter 客户端、LAN 发现或实体设备证据，因此 Mobile 仍为 0。
- **当前 vNext 矩阵：58.0 / 100，全部 P0 未达标，不可发布。** 取证文件为 `vnext/eval/evidence/phase4-performance-interim.json`：Domain 60、Game Loop 75、Content 60、Model 65、Desktop 60、Mobile 0、Long-play 75、Engineering 50。低分不是实现失败的代名词，而是如实反映缺少 PNG/导出 round-trip、Tauri RC、Android、目标设备性能和发布证据；不以局部真实模型成功推断这些维度完成。
- **叙事规则集评审（未计分）：** `ADR-003` 与 2026-08-17 规格提出在相同 WorldVersion/Run/RunState/Turn aggregate 内加入 `trpg`、`story_adventure`、`relationship_drama`、`hybrid`。现有 **58.0/100** 是前序 TRPG 矩阵的实现基线，不因文档增加分数，也不能与新的平台矩阵横向比较；Phase 0 contract freeze 后，scorecard 必须按新矩阵重新取证。
- **叙事规则集 Phase 0 / Mac 确定性切片（已实现，未过 gate，contract 已被 ADR-004 取代）：** `2ba5d57` 将 contract 升为 2026-08-17 / schema v2，`WorldDefinition` 固化 ruleset、章节/Flag/路线/ending definitions；唯一 `RunState` 保存关系 reason/once ledger、章节和锁定结局。`bb81a16` 增加雾港 native template、current-choice projection 和服务端 planned-choice endpoint；桌面页面仅发送 choice ID，不拼章节/结局 command。临时 DB 浏览器完成 create → 三次选择 → 好结局 → 回滚至第一回合后 → 刷新并恢复第二章选择；关系原因和 locked ending 均可见，控制台零错误。迁移 `0007_narrative_ruleset_contract` 仅更新 vNext contract metadata，不读取 legacy。该 v2 切片把 `relationship_dimensions` 放在角色卡内；ADR-004 要求先移至显式 `RelationshipDefinition` 的 schema v3 后重取相同证据，故不能将其作为最终内容建模完成证据。平台矩阵取证在 `vnext/eval/evidence/phase5-narrative-vertical-slice.json`：**56.75 / 100，所有 P0 仍未达到 80，不可发布。** 该数值刻意不复用 v2 未覆盖的旧 TRPG 长局/Android 分数。
- **真实模型补充证据（已实现，未过 gate）：** `fecce45` 将模型提示收紧为“只描述 Python 已确认结果”，并注入 ruleset/章节/路线/关系等只读上下文；单测确认模型没有状态裁判权限。台式机 Huihui 14B 在隔离数据库完成 v2 50 回合 SSE（最小 0.334s、中位 0.802s、最大 6.646s、一次非提交重试，recovery 正确），并完成雾港岚路线的三次选择与好结局（三段非空真实叙事）。原始取证为 `phase5-real-model-v2-50-turns.json` 与 `phase5-real-model-fog-harbor.json`。平台矩阵现为 **61.75 / 100，所有 P0 仍未达到 80，不可发布。** 仍缺 v2 500 消息重开、打包 Tauri、Android/LAN 与 release evidence。
- **v2 重开性能补充证据（已实现，未过 gate）：** `5d0b6e3` 使 benchmark 使用 schema v2；隔离 DB 中 500 条持久化 Turn 重开为 0.005s / 165475 bytes，revision 与完整历史都正确。平台矩阵现为 **62.25 / 100，所有 P0 仍未达到 80，不可发布。** 长局维度仍缺目标设备流式预算，不能上调到 80。
- **内容资产 contract 落地（未计分）：** 已将 WorldDefinition/API/桌面导入统一切换为 `lorebook.entries` 与 `character_cards`；旧 `lore` schema 和 endpoint 被明确拒绝。SillyTavern V3 导入会持久保留完整卡 payload、映射可解释字段和卡内世界书条目引用；API 可导出原始 V3 卡，也可通过 `GET /api/v2/world-versions/{id}/lorebook:export` 导出 World Info：导入条目原样回传 escrow 的原始对象，DZMM 原生条目则映射到安全的 World Info 字段。测试覆盖卡的导入 → WorldVersion 固定 → 导出 round-trip、World Info 保真导出、原生世界书安全导出，以及世界书选择/提升不改既有 Run。仍未完成 PNG metadata 文件输入、角色卡编辑界面与打包 Mac 作者旅程，因此内容互通与作者体验维度不加分。
- **跨规则集内容创建路径（未计分）：** 创建向导不再只在自定义 TRPG 显示 SillyTavern 导入；雾港剧情/关系模式同样会把导入的世界书与角色卡在单一 compose 前附着到新 WorldVersion。浏览器以 V3 卡完成“雾港 → 导入 → 创建 → 确认”，随后从该 version 导出原始卡和包含模板/导入两条目的 World Info；合并会在客户端拒绝重复 Lorebook/Character Card ID，避免模板规则或关系目标被静默遮蔽。`npm run build` 通过。证据为 `vnext/eval/evidence/phase10-cross-ruleset-content-authoring-interim.json`；这不替代编辑器、真实 PNG filechooser、打包 Mac 作者旅程或 Android 验收，平台矩阵仍为 **65.00 / 100**。
- **桌面内容资产导出（未计分）：** WorldVersion 创建确认页现在展示世界书条目数、角色卡清单，并可下载 World Info 与具备原始 payload 的 V3 角色卡。浏览器以正常操作完成雾港导入、创建和两次实际下载：World Info 保留模板/导入的 2 条条目，角色卡仍为 `chara_card_v3` 且名称正确；资产区和开局操作在 1600×900 首屏内可见、无横向溢出。证据为 `vnext/eval/evidence/phase11-desktop-content-export-interim.json`。它仍不是可重入的世界中心/编辑器、打包 WebView、PNG filechooser、Android 或评分提升证据；平台矩阵仍为 **65.00 / 100**。
- **多角色卡作者路径（未计分）：** 导入器现在累积多个来源，而不是以最后一张卡覆盖前一张；纯中文卡名得到稳定且不相同的内部 ID。雾港确认页区分“原生”与“SillyTavern V3”卡并为每张外部卡提供独立导出；如果外部卡与模板关系卡同名，创建会解释性拒绝，而不把名称猜成 relationship target。44 项后端测试、Ruff、桌面 build 均通过；浏览器覆盖两次连续导入、双下载、同名拒绝，以及 1600×900 与 Tauri 最小 960×600 的无横向溢出布局。证据为 `vnext/eval/evidence/phase12-multi-character-card-authoring-interim.json`。这仍不等于卡编辑/显式绑定、持久世界中心、打包 Mac 或 Android 验收，平台矩阵仍为 **65.00 / 100**。
- **World Center 生命周期（未计分）：** API v2 与桌面 World Center 现在以 World 为唯一管理根：可浏览最新版本/Run/世界书/角色卡计数，归档与恢复；永久删除先展示 aggregate manifest，再要求同时提交 manifest token 与精确世界名。通用 `POST /worlds/{id}/versions` 验证完整 WorldDefinition、乐观锁定 base version、附加新版本而不改既有 Run；旧 version、归档世界与错误名称都 fail-closed。45 项后端测试、Ruff、桌面 build 通过；浏览器以空态→创建→中心→归档→恢复→键入确认删除→空态完成旅程并检查 1600×900 settled 布局无横向溢出。证据为 `vnext/eval/evidence/phase13-world-center-lifecycle-interim.json`。目前没有完整的可视 WorldDefinition 编辑器，也没有打包 Tauri WebView lifecycle 证据，平台矩阵仍为 **65.00 / 100**。
- **世界书版本作者闭环（未计分）：** World Center 已提供受限 Lorebook 编辑器：作者可增删条目、编辑标题/内容/常驻或关键词触发/优先级，保存时调用 append-version API。浏览器完成雾港 v1 加入关键词条目→保存 v2，世界书由 1→2 条；原 Run 的 WorldVersion ID 保持 v1，新 WorldVersion ID 不同。密集编辑器在 1600×900 下无横向溢出，长表单按设计纵向滚动。证据为 `vnext/eval/evidence/phase14-lorebook-version-authoring-interim.json`。角色卡 payload、关系/章节/ending 还不能在该 UI 编辑；这不是打包 WebView 或评分提升证据，平台矩阵仍为 **65.00 / 100**。
- **最新打包 sidecar / DMG 冒烟（未计分）：** `30f7aee` 重新 PyInstaller 打包后，最新 Tauri debug `.app` 以隔离数据目录启动，`/health` 报告 `2026-08-17-lorebook`；经该 `.app` 内 sidecar 完成雾港三次选择 → `lan-dawn` → 回滚 → 重开，恢复到第二章三项 choice。`CI=true npx tauri build --debug` 同时成功生成 DMG，挂载后确认 `.app` 和 sidecar 存在。原始摘要在 `vnext/eval/evidence/phase5-packaged-app-sidecar.json`。本次是 packaged sidecar API 证据，不是 WebView UI 验收；debug app 仅 ad-hoc 签名且不能通过 strict bundle verification，因此不得给 Desktop/Engineering 维度加分。
- **当前打包 sidecar / DMG 冒烟（未计分）：** `bce4488` 代码已重新 PyInstaller 与 `CI=true npx tauri build --debug` 打包；实际启动该 `.app` 后，包内 sidecar 在隔离目录完成迁移并以 API v2 监听。通过这个包内 sidecar 完成当前雾港隐藏路线 → `bell-beyond-fog` → 回滚第一回合 → 重开，恢复为 revision 4 / `ch2` / 四个 choices；挂载 DMG 确认 sidecar 位于 `.app/Contents/Resources/backend-runtime/`。严格 `codesign --verify --deep --strict` 对 debug bundle 失败。证据为 `vnext/eval/evidence/phase8-packaged-current-sidecar.json`；它更新了当前代码的打包运行边界，不是 WebView UI、可访问性、正式签名或模型/Android 验收，不能加分。
- **叙事 command 权限收口（已评分，未过 gate）：** `d914ae6` 禁止含 `choices` capability 的 ruleset 走 raw `/turns` 或 `/turns:stream` 改状态；只有 `/choices` 才能把当前 choice 转为 Python planned commands。Android gameplay 同样拒绝 raw narrative stream，并增加受 pairing token 保护的 mobile choice endpoint。36 项后端测试、Ruff 均通过；取证 `phase6-choice-authority.json` 仅将状态裁决与 command 安全从 70 升至 **75**，当时平台矩阵为 **63.25 / 100**。
- **PNG 角色卡与完整雾港结局（已评分，未过 gate）：** `10be976` 接受 SillyTavern 标准 PNG `chara` metadata（`tEXt` / `zTXt` / `iTXt`，16 MiB image、8 MiB metadata 上限），保留解出的 V3 原始 payload，并在创建页加入本地 PNG 导入入口。雾港原生模板此前虽有“隐藏结局”概念但实际不可达；现增加受限 `unite-witnesses` choice、固定 Flag/关系 event，并以当前模板确定性覆盖岚/沈砚好结局、普通、坏与隐藏结局，另覆盖 once/cooldown 拒绝零写入。隔离 Host + 本地浏览器实测隐藏路线并确认多条关系 reason 与结局页；Host 重启遗留的失效 Run 也会静默清理。`pytest -q` 为 42 passed，Ruff 与桌面 build 通过。取证 `vnext/eval/evidence/phase7-content-and-endings.json`：内容 60→65、剧情完整性 75→**80**、桌面 70→75，平台矩阵现为 **65.00 / 100**；其余 P0 仍未达 80，不可发布。该证据不把合成 PNG 测试当真实卡 filechooser E2E，也不把浏览器当打包 Mac 验收。
- **安全 LAN gameplay Host（未计分）：** Mac Tauri Host 已有显式“局域网玩法”开关；它重启 sidecar 于 `127.0.0.1` / `0.0.0.0`，失败时恢复上一次监听。LAN 开启时，非 loopback 请求仅允许 `/api/v2/mobile/*`：世界、模型、Host 管理和能力发现均在 handler 前被拒绝；loopback 仍可批准/撤销配对。43 项后端测试（含远程来源的配对→mobile choice）与 Ruff、桌面 build、Rust format/check、PyInstaller 与 debug `.app`/DMG build 均通过；隔离 sidecar 实测非 loopback Host 路径 403、mobile pairing 200。证据为 `vnext/eval/evidence/phase9-lan-host-security-interim.json`。这不是打包 WebView 点击、Android UI/恢复、Wi-Fi 发现、断线 soak 或 Mac+Android 实机验收，Mobile 仍为 0，平台矩阵仍为 **65.00 / 100**。
- **schema v3 内容/关系边界（未计分）：** `ddb8ac2` 后，当前实现把角色卡内 `relationship_dimensions` 移至 `story.relationships[]`，其中的 dimensions 独立声明 initial/min/max，relationship event 仅引用 relationship ID；Python 按定义边界 clamp，RunState 仍只存已应用 event 的结果。测试明确拒绝卡内关系字段与未知 relationship，并证明同一角色卡可在不同 WorldVersion 使用不同关系初值/边界；雾港四结局、回滚和 mobile choice 回归保持通过。fresh isolated DB 的 500 Turn 重开为 0.005s / 165475 bytes，证据为 `vnext/eval/evidence/phase16-schema-v3-reopen-500-interim.json`。本项替代 v2 contract 的内容建模证据，但没有真实模型、打包 WebView 或 Android 实机旅程，故不改变当前 **65.00 / 100** 的保守分数。
- **主题系统（未计分）：** 桌面现在可在雾夜、纸页和琥珀间切换；选择保存在 `dzmm-next-theme`，刷新后恢复。1600×900 全页目测确认三套主题的创建页层级与浅色告警对比，Chrome 自动化确认三主题在 390×844 无横向溢出。`npm run build`、`cargo fmt --check` 与 `cargo check` 均通过；证据为 `vnext/eval/evidence/phase17-theme-interim.json`。这是 source-browser 主题验收，不替代打包 WebView 或成熟度加分。
- **schema v3 本机真实模型矩阵（未计分）：** 本机 Ollama 的 `sakura-eclipse-12b-32k:latest`（12.2B）在 fresh isolated DB 完成雾港岚/沈砚/中立/坏/隐藏五条路线：15 次 choice 均有非空真实叙事，每条路线在锁定结局后回滚第一回合并重开为第二章、未锁 ending。延迟 min/median/max 为 8.506/17.526/28.692 秒。选择端点此前漏映射 `NarrationError`，会把模型 timeout 变为无信息 500；现改为 502 且保留异常类别，模型 read timeout 为 120 秒、输出上限为 96 token，错误时不提交 RunState。取证 `vnext/eval/evidence/phase18-local-sakura-schema-v3-fog-harbor-matrix-interim.json`。台式机 Huihui 14B/22B 的 `/v1` endpoint 当前超时，Sakura 只作为本机工程证据，不提高 65.00/100，也不满足真实模型最终 gate。
- **schema v3 Mac 包冷启动/sidecar（未计分）：** `--onefile` 冻结 sidecar 的首次监听约为 35 秒，超过桌面 Host 20 秒就绪门槛，造成错误的“Host 未就绪”。现切换为同名目录式 PyInstaller runtime，Tauri 的资源解析同步指向其中的可执行文件；新鲜隔离数据目录下，包内 sidecar 1.996 秒返回 `/health`。实际启动 `DZMM Next.app/Contents/MacOS/dzmm-next-desktop`（而非直接启动 sidecar）时，WebView 的 `onMounted → invoke(start_backend)` 路径在 0.841 秒暴露健康端点。重新构建 debug `.app`/DMG 后，包内 sidecar 实测 schema v3 雾港创建 → 三次 choice → `lan-dawn` → 回滚第一回合 → 重开，重开状态与 revision 4 的回滚状态完全一致；挂载 DMG 确认目录式 runtime 存在。证据为 `vnext/eval/evidence/phase19-schema-v3-packaged-sidecar-cold-start-interim.json`。这仍不是完整 WebView 点击/可访问性、正式签名、模型或 Android/LAN 物理验收，因此不提高当前 **65.00 / 100**。
- **Android 原型只读审计（未计分）：** 未提交的 `vnext/mobile/` Flutter 原型可申请配对、读取 Run 和发送 TRPG raw stream，但尚未消费 narrative choice、章节/关系/结局投影或恢复 contract；`flutter analyze` / `flutter test` 均因模板测试引用不存在的 `MyApp` 而失败。当前 `adb devices` 与 Flutter 无 Android 或无线设备，不能构造实机 LAN 证据。为保留未知所有权的未提交文件，本轮没有改写或提交该目录；Mobile 仍为 0。

### 下一关

用真实 SillyTavern PNG 完成打包 Mac 的导入→开局→导出 round-trip，并以 Huihui 14B 覆盖剧情结局与回滚长局；随后迁入 TRPG capability 并验证 hybrid，最后推进 Android/LAN RC。达到每项证据的实际门槛前，不得从 legacy 目录复制领域模型或 API。
