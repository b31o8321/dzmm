# DZMM vNext 玩家视角重定基线

日期：2026-08-21  
老版基线：`/Users/norman/development/dzmm`，`main@df38037`  
实现目标：`/Users/norman/development/dzmm/.worktrees/dzmm-vnext`，`feature/dzmm-vnext@4c43edc`

## 结论

vNext 当前约 30/100。它已经具备本地 SQLite、Python 状态裁判、WorldVersion、Run、
选择、结局、回滚和 portable bundle 等基础设施，但尚未形成玩家可完成的产品闭环。
此前约 80 分的矩阵混合了代码存在、接口取证、模拟器自动点击和真实可玩性；这些证据只能证明
“框架能运行”，不能证明玩家可以快速设置、进入故事并沉浸地完成一局。

发布评估从本文件开始改用玩家旅程。以下任一 P0 旅程不成立时，真实可玩性最高只能记 30 分，
无论后端、构建或长回合脚本是否通过。

## 玩家与任务

第一目标玩家是使用本地或 OpenAI-compatible 模型、独自进行 AI TRPG/互动叙事的中文玩家。
他打开应用不是为了理解 Host、schema、revision 或 aggregate，而是为了：

1. 快速确认模型可用；
2. 选择或创建一个世界；
3. 开始一局有开场、有角色、有目标的故事；
4. 在每次行动后清楚知道系统正在生成、失败还是已经完成；
5. 看见叙事、对话、选择和状态反馈自然衔接；
6. 完成结局，并能从同一世界继续或另开一局。

## 非目标

- 不恢复远程 Host、LAN discovery、mDNS、QR、pairing 或同一 Run 多端写入。
- 不把老版 `GameView.vue`、多 Agent 编排或全部外围功能原样搬入 vNext。
- 不以 TTS、地图、战斗面板或内容市场替代首个可玩闭环。
- 不让 LLM 直接决定骰子、物品、关系、章节和结局状态。

## 老版与 vNext 差距

| 玩家任务 | 老版 main | vNext 当前事实 | P0 目标 |
| --- | --- | --- | --- |
| 配置模型 | 新增、编辑、删除、测试、设默认；Session 可换 GM 模型 | desktop/Android 只有新增、列表和 Probe；Android 的 default key 未接通 | 三端共享 CRUD、Probe、默认模型与引用冲突语义 |
| 新开一局 | 从跑团存档选择已有世界/剧本/模型创建 Session | compose 原子创建 World、Version、Hero、Run；没有从已有 World 创建 Run | World 可复用；明确“继续 Run / 开始新 Run” |
| 开场 | 空 Session 自动以 `opening_hook` 请求 GM 开场 | 初始 State 没有 opening Turn；UI 直接显示 choice | Run 创建后先生成并持久化开场叙事 |
| 回合等待 | SSE 流式叙事、发送按钮 loading、文字逐步出现 | desktop 使用非流式 POST；Android 是阻塞 MethodChannel；游玩页只禁用按钮 | 立即可见的阶段状态、流式文本或心跳、耗时、取消与重试 |
| 叙事和对话 | `<narrative>`、`<say>`、PC 行动、选项和事件分层展示 | Turn 只有单段 `narrative`；开场为空；技术状态占据视觉首位 | 统一的 story beat：旁白、角色对话、玩家行动、GM 反馈、引导 |
| 玩家输入 | 自由行动、行动模式、建议和 GM choices 共存 | narrative ruleset 显示自由输入却拒绝非 choice 状态变化 | UI 只展示当前规则真正支持的输入；自由行动走可验证的 narrative intent |
| 结束与重玩 | 剧本完结后可创建续作，新 Session 重置回合并继承世界 | ending 只锁状态并显示类型；无结局叙事页和新 Run 动作 | 结局叙事、回顾、回到世界、同世界新 Run、回滚 |
| 恢复 | 消息和状态重载，最近回合可重试/编辑 | Run snapshot、rollback、reopen 基础较好，但生成中状态不可恢复 | pending operation 明确；失败/取消零提交；重开解释上次发生了什么 |

## 玩家旅程

### J1 首次设置

入口：首次启动或“模型”。  
完成：玩家在不理解协议内部细节的前提下保存并测试模型，设为默认，然后进入世界。

要求：

- 首次配置在 3 分钟内完成，不含模型下载或第三方服务安装时间。
- 协议、Base URL、模型名作为完整档案编辑；API key 不回显明文。
- 操作后 200ms 内出现反馈；Probe 必须区分网络、HTTP、协议、空内容和超时。
- 删除被 Run 使用或删除默认档案时给出可执行的解决办法。

### J2 从 World 开始或继续 Run

入口：“世界”。  
完成：玩家能理解 World 是可复用舞台，Run 是一段独立故事；选择继续或新开时不会误写已有 Run。

要求：

- 世界卡显示内容摘要、已有 Run、最近游玩和下一步动作。
- “继续上次 Run”和“开始新 Run”是两个明确动作。
- 新 Run 选择 Hero、模型和可选开场偏好；确认前不写运行状态。
- 创建 World 可以建议立即开局，但不能隐藏 World/Run 的区别。

### J3 开场与正常回合

入口：新 Run 或继续 Run。  
完成：玩家先看到能代入的开场，再选择或输入行动，并得到连续的叙事结果。

要求：

- 开场至少包含场景、当前处境、一个可感知角色或线索、下一步引导。
- 技术字段默认不进入叙事主视区；状态、章节和背包进入可收起区域。
- 选择与自由行动不得出现“UI 可输入、后端必拒绝”的假能力。
- 每回合展示玩家行动、旁白、角色对话、结构状态反馈和新的行动入口。

### J4 慢模型、失败、取消和恢复

入口：任一 LLM 操作。  
完成：玩家始终知道系统处于哪个阶段，并能安全退出、取消或重试。

共享阶段：`preparing -> connecting -> generating -> applying -> completed`，以及
`failed / cancelled / restored`。

要求：

- 操作开始 200ms 内显示阶段；超过 8 秒显示耗时和恢复说明。
- 生成阶段优先流式展示；不能流式时持续显示心跳和当前阶段。
- 取消或失败不得增加 revision、turn_count 或留下半条 assistant/Turn。
- 重开应用时能够恢复已提交的 Turn，并明确说明未完成操作没有写入。

### J5 正式结局与同世界重玩

入口：ending 被 Python 锁定。  
完成：玩家看见结局叙事和本局摘要，随后选择回看、回滚、回到世界或开始新 Run。

要求：

- `narrative_key` 不能直接作为玩家看到的最终文案。
- 结局页包含结局标题、叙事、关键选择/关系摘要和本局时长/回合数。
- 新 Run 生成新 ID 和初始状态，不覆盖已结束 Run。

## 三端一致性矩阵

核心语义必须一致；布局可以适应平台。

| 能力 | macOS / Windows | Android | 共同验收 |
| --- | --- | --- | --- |
| 世界 | 列表 + 详情分栏 | 列表进入全屏详情 | 继续 Run、新 Run、归档/恢复语义相同 |
| 新 Run | 详情主动作或快捷键 | 拇指可达主按钮 | 同一 use case、校验、默认模型和结果 |
| 游玩 | 叙事主栏 + 可收起状态栏 | 沉浸单栏 + 状态 bottom sheet | 同一 story beat、阶段状态和恢复结果 |
| 模型 | 表格/编辑面板 | 卡片/编辑 sheet | CRUD、Probe、default、引用冲突相同 |
| 结局 | 结局画面 + 后续动作 | 全屏结局 + 底部动作 | 回看、回滚、世界、新 Run 相同 |

## 技术含义

1. `compose_world` 不能继续承担唯一的新 Run 入口；新增共享 `create_run` use case。
2. opening 是持久化 story beat，不是 renderer 临时拼接的一段欢迎文案。
3. 回合状态机进入 Experience Contract 和 typed ports；renderer 只负责呈现。
4. narrative 展示模型至少区分 narrator、speaker dialogue、player action、system outcome。
5. desktop FastAPI 与 Android embedded Python 必须调用同一应用服务或同一组纯领域函数；禁止各自重新实现规则。
6. 旧版只作为玩家语义和回归参考，不作为 vNext 依赖源。

## 里程碑

1. **M1 玩家闭环骨架**：共享 `create_run`、World 详情、开场 story beat、继续/新 Run、结局后动作。
2. **M2 回合沉浸与恢复**：共享阶段状态、流式/心跳、取消、失败零写入、对话分层。
3. **M3 首次设置一致性**：ModelProfile CRUD/default/probe 和跨端恢复。
4. **M4 三端安装验收**：macOS、Windows、Android 真机完整旅程和 30 回合恢复。

每个里程碑必须更新 Active Delivery Index；只有真实安装旅程通过，才允许提高玩家可玩性分数。

