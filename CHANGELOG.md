# 更新日志

按 [Keep a Changelog](https://keepachangelog.com/) 风格，版本对应 git tag。

## 版本号约定

`MAJOR.MINOR.PATCH`：
- **MAJOR**：测试 / 正式 / 季度级大版本（0 = 测试阶段；1 = 正式发布之后）
- **MINOR**：核心功能变更（如「剧本驱动」「编年史系统」整套机制）
- **PATCH**：小修复 / 小增强（bug fix、UI 微调、文档）

历史版本（v0.1 - v0.13）属于测试期 PATCH 增量；自 0.0.14 起改用三位数显式标记。

## [v0.2.0] - 2026-05-01

**主题：Vibe Coding 风格向导式创建 + v0.1.9 修复打包**

针对**本地 12B 模型**优化，把一次性 outline 调用改成 6 步引导式生成。每一步玩家审阅 / 编辑 / 重新生成 / 接受。每步独立 LLM 短 prompt，本地模型也能稳定产出有质感的世界 + 角色 + 剧本。

### 新增（向导式创建）
- **6 步骤 wizard**（路由 `/sessions/wizard`）：
  1. 设置（选 wizard 模型 / GM 模型 / summarizer 模型 + genre + 主题）
  2. 基础设定（200-300 字名字/年代/核心冲突）
  3. 世界扩展（600-1200 字 world_md）
  4. PC 角色卡（profile_md：基本信息/性格/背景/能力/物品/弱点）
  5. 主要 NPC（3-5 个 + 玩家选钉住）
  6. 剧本大纲（chapters/main_characters/ending/opening_hook）
  + 审阅 + 创建（atomic 写 World + Character + Session + 钉住 NPC + Screenplay）
- 每步 4 个动作：✏️ 编辑 / 🔄 重新生成 / ✏️ 我自己写 / ⏩ 接受继续
- 模型可分开选：wizard 用 12B+ think 模型（创建慢但质优），GM 用 7-8B 快速模型
- 后端：`api/routes_wizard.py` 6 个端点 + `service/wizard.py` 6 个函数 + `prompts/wizard_*.py` 5 个 prompt 模板（每个聚焦短 prompt）
- 前端：新页面 `WizardView.vue`（964 行 inline state 共享）+ `api/wizard.ts` + `components/wizard/WizardStep.vue` 通用步骤组件
- SessionsView「+ 新开一局」改 2 tab：🪄 **向导式（推荐，默认）** / ⚡ 快速创建（预设）

### v0.1.9 修复（打入此版本）
- **hidden_event dedup**：同 (subject, kind) 已 active 时更新而非新建（治实玩 6 次重复 emit）
- **NPC NER 严格化**：频率门槛 2→3 + 扩充停用词表（修道院/大门/然后/雨水/离开 等高频误判词）+ 首字动词/虚词时要求 ≥4 字（治实玩抓出 7 个垃圾 NPC）
- **parser flush 强制闭合**：stream 结束时未闭合 tag emit `ParseError` + 合成 `TagComplete` 用截断内容（治「Unclosed tag <choices>」反馈）
- **dice 随机性 prompt**：dice 标签字典加显式「必须真实随机！d20 1-20 每次不同」+ 简单兜底建议（治实玩 dice 总是 d20=9 的问题）
- **NER 清理按钮**：`DELETE /sessions/{id}/npcs/auto_created` + DebugView NPC tab 加「🧹 清理 NER 自动创建」按钮（让玩家清掉历史误抓的 stub）

### 数据库
无 schema 变化（向导只是创建已有表的 row）

### 测试
- 后端 265 → 290（+25：18 wizard + 7 v0.1.9 fixes）
- 前端 build 通过
- 新组件：`WizardView.vue` / `WizardStep.vue`

---

## [v0.1.8] - 2026-05-01

**实玩反馈热修：导出 500 + PC 名漂移成 #**

### 修复
- **存档导出 JSON / MD 全部 500** —— 用户反馈「网络错误，无法导出」。根因：session 名含 CJK 字符（如「修女」）时，`_safe_filename` 用 `c.isalnum()` 不剔除中文（Python 对 CJK 也返 True），导致 Content-Disposition header 含 latin-1 不能编码的字符 → starlette 抛 UnicodeEncodeError → 500。修：
  - `_safe_filename` 强制 ASCII（`c.isascii() and c.isalnum()`）
  - 新加 `_disposition_header()` 同时输出 ASCII fallback `filename="..."` 和 RFC 5987 `filename*=UTF-8''<percent-encoded>`，浏览器能恢复中文文件名
  - 加回归测试：CJK 名字导出不再 500
- **PC 名漂移成 `#`（实玩观察）** —— 一些本地 LM Studio 模型把 `#` 当成 PC 占位符（实玩中看到 `<pc_action>#站起身`、`记下了#的特征`、`攻击#`）。`_repair_pc_name` 加 placeholder repair：
  - 新模式 `_PLACEHOLDER_PC_RE`：识别 `#` / `□` / `★` 后接 CJK 字符或 CJK 标点，替换为 character.name
  - 拒绝 markdown heading：`## 基本信息` 不被替换（前后有 `#` 或空白）
  - `<say>` 内的 NPC 对白不动（保 NPC 自由用 `#` 谈话）

### 测试
- 后端 260 → 265（+5：1 个 CJK 导出回归 + 4 个 # placeholder 修复）

---

## [v0.1.7] - 2026-05-01

**修复 + 新增**

### 修复
- **SSE 流式回归（v0.1.6 重构引入的 P0 bug）** —— `useGameTurn` 里的 `Turn` 对象是 plain 对象，`turn.narrative += text` 走的是局部变量引用，绕过 Vue reactive proxy → 模板不重渲染 → narrative 流式过程中空白，刷新页面才显示。修复：用 `reactive()` 包 turn 对象，让 mutations 走代理。
- **剧本生成超时** —— outliner 默认 60s 超时（继承 ModelConfig.timeout），本地 7B 模型生成 2000 token 经常 90-180s 超时挂掉。修复：
  - `routes_screenplay._build_outliner_client` 强制把 client.timeout 拉到 600s
  - `screenplayApi.generate` axios timeout 30s → 600_000ms
  - `SessionGenerateView` loading 文案改成「通常本地模型 30-180s，云模型 10-30s」+ >90s 提示切云模型 + >240s 提示删档重建

### 新增
- **`service/activity_log.py`** —— 结构化 JSONL 活动日志，写到 `~/.dzmm/activity.jsonl`（5MB rotation）。`log_event(session_id, kind, **payload)` 一行一事件，便于 grep / debug
- 已接入 `screenplay.generate_screenplay`：emit `screenplay_generate_start` / `screenplay_generate_end`（含 duration_ms + raw_chars + chapter 数）/ `screenplay_generate_error`（含解析错误或 LLM 异常）
- v0.1.8 会接入 run_turn / state_apply / parser，并加 `GET /sessions/{id}/activity` 端点 + DebugView 展示

---

## [v0.1.6] - 2026-05-01

**主题：项目结构重构（行为零变更）**

把累积下来的几个超大文件按职责拆成包，便于维护。所有重构都有 260 个测试做回归保护。

### 后端
- **`service/state_apply.py` 1091 行 → 包**：12 个文件
  - `state_apply/__init__.py` re-export 公开 API
  - `state_apply/_impl.py` (~114 行) — apply_tags dispatcher + import 各 handler
  - 11 个独立 handler 模块：`state_change` / `npc` / `npc_relation` / `plot_event` / `era` / `character_xp` / `pc_goal` / `pc_mood` / `hidden_event` / `screenplay` / `recall`
- **`api/routes_sessions.py` 1134 行 → 包**：10 个文件
  - `__init__.py` aggregator + `__setattr__` proxy（让测试 monkeypatch `routes_sessions.build_client` 仍能镜像到子模块）
  - `_common.py` — DI deps + 共用 helper
  - 9 个端点模块：`base` / `messages` / `turn` / `threads` / `npcs` / `goals` / `hidden_events` / `feedback` / `export`
- **`service/game.py` 818 → ~620 行**：抽出 `name_repair.py` + `npc_dossier.py`
- **`prompts/gm_template.py` 542 → ~470 行**：抽出 `gm_few_shot.py`（保 byte-equal）

### 前端
- **`views/GameView.vue` 853 → ~530 行**：拆 composable + 子组件
  - `composables/useGameState.ts` (113 行) — reactive state 集合 + applyXXX 函数
  - `composables/useGameTurn.ts` (224 行) — sendAction + 流式 onTag/onNarrative/onDone
  - `components/game/MessageList.vue` (128 行) — 消息列表渲染（SpeakerBubble + parseParts/displayParts + events 按钮 + choices）

### 文档
- 新增 `docs/ARCHITECTURE.md`（~270 行）—— 顶层结构 / 后端 / 前端目录约定 / 跑团一回合数据流图 / DB schema / 6 个关键设计模式
- 老 plans v0.1 ~ v0.8 归档到 `docs/superpowers/plans/archive/`（保留 roadmap + v0.1.0 现役 plan）
- README 路线图：13 个版本逐行 → 最近 4 版 + 老版本折叠 + 显式指向 CHANGELOG / ARCHITECTURE

### 测试
- 后端 260/260 全过（行为零变更）
- 前端 build 全过

---

## [v0.1.5] - 2026-05-01

**新增：启动日志面板**

为了诊断「正在启动后端」卡死的情况，给每个启动阶段都加了日志查看入口。

### 前端
- `BootGate.vue` 各启动阶段（choose_mode / backend / ollama_starting / ollama_missing）加「📋 启动日志」按钮
- 弹 dialog 显示 timestamped 日志条目，颜色区分（红=错误/stderr、黄=警告、绿=stdout、灰=system）
- 「📋 复制全部」按钮把日志复制到剪贴板，方便贴给开发者
- 前端记录：BootGate 挂载、模式选择、start_backend 调用、/health ping 进度、/system/status 查询、Ollama 启动 / 轮询、错误等

### Tauri 后端
- `lib.rs` `spawn_backend` 改 `Stdio::piped()`（之前是 `null`，stdout/stderr 被吞掉）
- 起两个 thread 用 BufReader 逐行读 stdout / stderr
- 用 `tauri::Emitter::emit` 发 `backend-log` 事件给 webview，含 stream / line / 时间戳
- 前端 `@tauri-apps/api/event` 监听 `backend-log` 事件 push 到日志数组

### 用户能看到什么
- Tauri spawn backend 时打印 `spawned: <path>`
- 后端 PyInstaller 启动错误（找不到 DLL / 端口被占等）会作为 stderr 行出现
- 后端 uvicorn / FastAPI 的启动日志（init_db、seed_data 等）作为 stdout 出现
- 前端 ping /health 失败次数、超时时长

启动卡死时，点开日志直接看 backend 在哪一步死了或为什么 spawn 失败。

---

## [v0.1.4] - 2026-05-01

**新增：LM Studio 本地模型支持**

### 新增
- 模型类型新增 `lm_studio`（LM Studio 暴露的 OpenAI 兼容 `/v1/chat/completions` 端点）
- ModelsView 新建 / 编辑对话类型选择器加「LM Studio 本地」
- 切换类型时自动填默认 base_url：
  - Ollama → `http://localhost:11434`
  - LM Studio → `http://localhost:1234/v1`
  - OpenAI 兼容 → `https://api.openai.com/v1`
- LM Studio 不需要 API Key（OpenAICompatClient 在 api_key 为空时不发送 Authorization header，避免本地服务被空 Bearer 困扰）
- model_name 字段按类型显示对应 placeholder

### 测试
- 后端 259 → 260（+1：lm_studio factory 路径）

---

## [v0.1.3] - 2026-05-01

**新增：删除存档**

### 新增
- `DELETE /sessions/{id}` 端点 —— cascade 删除所有 per-session 数据：messages / NPCs / relations / plot_threads / eras / timeline / char_state / story_summary / pc_goals / hidden_events / screenplays + revisions / feedbacks
- World / Character / ModelConfig **不受影响**（多 session 共享）
- SessionsView 表格操作列加「🗑️ 删除」按钮 + 二次确认对话框（显示存档名 + 已进行回合数 + 警告无法撤销）
- sessionsStore.remove() 方法

### 测试
- 后端 256 → 259（+3：cascade 验证、404、世界角色不被误删）

---

## [v0.1.2] - 2026-05-01

**修复：补上从未存在的「设置」页**

v0.8 加 Tauri 自动更新时，BootGate 的 toast 写「点击设置中的『检查更新』」——但**设置页从来没建**。此版本补上：

### 新增
- **`/settings` 路由 + `SettingsView.vue`** —— 集中页面，含三块：
  - **版本与更新**：显示前端 / 后端版本（不一致红字提示）+「检查更新」按钮 +「下载并安装」按钮（仅有更新时出现）+ 更新说明展示
  - **引导 / 帮助**：「重新查看引导」按钮（清 tourCompleted localStorage 跳回 /welcome）+ 帮助页链接
  - **开发者**：调试模式触发序列说明（↑↑↓↓←→←→）
- SidebarNav 加「⚙️ 设置」入口（桌面 + 移动端）
- BootGate toast 文案改为「打开侧栏的「⚙️ 设置」点「检查更新」安装」（指向真实路径）

---

## [v0.1.1] - 2026-04-30

**主题：调试模式 + e2e 修复**

### 新增
- **调试模式（Konami 风格触发）** —— 任意页面键入 `↑↑↓↓←→←→` 切换 debug 模式（toggle）；持久化到 localStorage
- **DebugView 页（`/debug`）** —— 集中展示所有正常游玩中被隐藏 / 未揭示的数据：
  - 完整剧本（含未来章节、未出场 NPC、ending 剧透）
  - hidden_events（active + resolved）含 GM-only consequence
  - 全部 NPC 字段（无视 reveal mask）—— purpose / archetype / 全 emotion / affinity
  - plot_threads / token 累计 / 最近消息原文 / feedback
- SidebarNav debug 开启时显示「🐛 DEBUG MODE」红色 watermark + 「🐛 调试」link

### 修复
- **e2e workflow CI 失败** —— 通过多重防御让 CI 通过：
  - `vite.config.ts` 用 `fs.readFileSync` 替代 `import ... with { type: 'json' }`（Node < 20.10 不支持）
  - playwright `webServer` 用 `url` 替代 `port` readiness（实际 HTTP 探测，避 IPv6/IPv4 不一致）
  - Vite 显式 `--host 127.0.0.1` 强制 IPv4 binding（CI Ubuntu localhost 默认解析 IPv6）
  - `addInitScript` 预设 onboarding 完成 localStorage（绕过 WelcomeView 冷启动 flake）
  - smoke test 适配 v0.1.0 流程：4 个 dropdown 用键盘 Down + Enter 选择 + `/sessions/generate/:id` loading 页步骤
  - `mock_backend.py` StubModelClient 智能化：检测 outliner system prompt 返回 JSON outline；GM 调用返 narrative
  - `@playwright/test` 升级到 ^1.59.1

### 不需要后端改动
所有调试数据通过现有 API 暴露（reveal 限制只在 GM prompt 注入时生效，HTTP 响应是完整数据）。

---

## [v0.1.0] - 2026-04-30

**主题：剧本驱动跑团（首个 MINOR 版）**

把跑团从「GM 自由发挥」改成「预生成剧本大纲 + GM 围绕大纲展开」。开新档时调 LLM 生成结构化剧本，GM 按章节推进；玩家重大决策可以触发后续大纲重写；故事完结后可生成续集（PC 状态延续）。

### 新增
- **开档同步生成剧本**：`POST /sessions/{id}/screenplay/generate` 调 outliner LLM 输出结构化 JSON（章节 / 主要 NPC / 关键事件 / 结局 / 不剧透开场白）
- **5 套 genre 模板** + 自定义：悬疑探案 / 英雄成长 / 政治阴谋 / 灾难求生 / 恋爱攻略
- **生成 loading 页**（`/sessions/generate/:id`）—— 倒计时 + tip 轮播 + 完成后展示 opening_hook 引子作为开局
- **剧本进度页**（`/play/:id/screenplay`）—— 当前章节 / 主线 [done][pending] / 支线 [done][optional] / 主要 NPC / 完结条件 / 进度条
- **GameView 头部加「📜 剧本」link** + 完结时蓝色 banner「📖 续写下一章」
- **重大决策手动标记**：玩家可点「⚡ 这是重要决定」按钮添加 ScreenplayRevision（v0.1.1 接 outliner 异步重写）
- **续作机制**：concluded screenplay → POST `/screenplay/continue` 基于 ending 生成 v2 大纲，PC 状态延续，旧 screenplay parent_screenplay_id 链
- **4 个新 GM 标签**：`<chapter_advance/>` / `<event_complete chapter=N event=M type=main|optional/>` / `<plot_turn impact=major|minor description=.../>` / `<ending/>`
- **GM prompt 铁律 24** 剧本进度遵守 + 4 个标签字典文档
- **key_facts 注入「## 当前剧本进度」段** —— GM 每回合知道当前章节、待演主线、可选支线、未出场重要 NPC、完结条件

### 数据库
- 新表 `screenplays`（id, session_id, version, genre, custom_prompt, chapters_json, main_characters_json, ending_md, opening_hook, current_chapter, completed_events_json, parent_screenplay_id, status, created_at, concluded_at）
- 新表 `screenplay_revisions`（append-only log）
- 由 `Base.metadata.create_all` 自动建表

### API 新增
- `POST /sessions/{id}/screenplay/generate`
- `GET /sessions/{id}/screenplay`
- `POST /sessions/{id}/screenplay/mark_decision`
- `POST /sessions/{id}/screenplay/continue`
- `GET /sessions/{id}/screenplay/revisions`

### 测试
- 后端 225 → 256（+31：outliner 5 / screenplay service 3 / routes 7 / parser 4 / state_apply 7 / game 3 / gm_template 2）
- 前端 build 通过；新组件 GenreSelector / SessionGenerateView / ScreenplayView

### 待办（v0.1.1）
- `<plot_turn impact="major"/>` 触发的异步 outliner 重写（v0.1.0 只记 ScreenplayRevision 占位）
- ScreenplayView 历史 revisions 时间线展示

---

## [v0.0.14] - 2026-04-30

**主题：玩家反馈收集**

### 新增
- **应用内反馈** —— GameView header 加「💬 反馈」按钮，新组件 `FeedbackDialog.vue` 弹窗输入；4 种 kind（bug / suggestion / praise / other）
- 反馈绑定到 session：自动记录 `turn`、可选 `message_id`、`created_at` 时间戳，方便开发者结合上下文复盘
- API：`POST /sessions/{id}/feedback`、`GET /sessions/{id}/feedback`
- 反馈被纳入 `/export?format=json|md`：JSON 加 `feedbacks` 字段；Markdown 加「## 玩家反馈」段
- 内容长度上限 4000 字、空内容返 400

### 数据库
- 新表 `feedbacks`（id, session_id, turn, message_id, kind, content, created_at）
- 由 `Base.metadata.create_all` 自动建表，无 ALTER 迁移

### 测试
- 后端 217 → 225（+8：post / list / 校验 / 404 / export json+md / kind 归一化 / 空内容 / 长度上限）
- 前端 build 通过

---

## [v0.13] - 2026-04-30

**主题：实玩反馈第三波 — SSE 流式回归 + 推进义务加狠 + plot 去重加严**

### 修复
- **SSE 流式渲染回归（v0.10 引入的 P0 bug）** —— GameView 模板在 GM emit 第一个 `<say>`/`<pc_action>` 后切换到 `parseParts(rawContent)`，但 rawContent 不含 narrative 文本 → 整段消失等回合结束才出现。修复：`displayParts(t)` 总是先展示 `t.narrative`（流式累加），再展示 rawContent 中的 say/pc_action 部分（跳过 narrative 部分避免重复）
- **plot_event 去重失效** —— v0.12 阈值 0.7 在某些场景下没拦住。改造：
  - normalize 后比较（全角→半角空格、CJK 标点→ASCII、lowercase）
  - 完全相同短路命中
  - 阈值降到 0.6
  - 覆盖所有创建 thread 的 type（new_quest / hook_introduced / major_event / location_entered）
- **关键信息推进义务（铁律 22 加狠）** —— v0.12 不够具体，GM 仍反复反问。改写：
  - 5 类问句明确要求字面答案（问名字 → 2-4 字汉字专有名词；问地点 → 具体地名；问时间 → 具体时间；问数量 → 具体数字）
  - 禁止句式黑名单：「他可能告诉你...」「等你决定再说」「时机未到」「以后会知道」
  - NPC 反问 PC 同一问题超过 1 次 = 失败
  - 「重复问题 = 重复给答案」铁律
  - few_shot 加正例（陈子轩/九龙黑街/清风茶寮 全名地点直接给）+ 反例（拒绝拖延循环）
- **铁律 23 加狠** —— choices 与上回合 ≥80% 重合 = 失败；同一 choice 被点 ≥2 次必须有不同结果

### 新增
- **后端版本对比警告** —— SidebarNav 拉 `/health.version` 与前端 `__APP_VERSION__` 对比，不一致时红字 ⚠️ 提示「请重打包：python packaging/build.py」
- **`/export` 路由注册防御测试** —— 用真实 ASGI client 测试 `GET /sessions/{id}/export?format=json` 返回 200，防止 main.py 重构时丢路由

### 测试
- 后端 204 → 217（+13）
- 前端 build 通过

---

## [v0.12] - 2026-04-30

**主题：实玩反馈第二波 — 姓名漂移根治 + 推进义务 + 帮助页**

v0.11 实玩 5 条问题集中收口。版本号显示、姓名漂移多重防御、数值 tooltip、帮助页、剧情推进。

### 新增
- **页面显示版本号** —— SidebarNav 底部 + GameView header 角落显示 `v{version}`，从 package.json 编译期注入；`/health` 端点也暴露后端 `app_version`
- **PC 姓名 repair 兜底**（再次根治 Riku → 林峰 类漂移）：
  - 后端在 GM 输出持久化前扫 `我叫 X / 我是 X / 在下 X / 鄙人 X / 叫我 X / 本人(是) X / 敝人 X` 6 类自报家门模式
  - `<say speaker="...">` NPC 对白块用占位符 mask 后 repair 再恢复，避免误改 NPC 名
  - `_FEW_SHOT_EXAMPLE` 里的 PC 名硬编码改为 `{character_name}` 占位符，防止本地 7B 模型把范例名当成 PC 名
  - GM prompt 铁律 16 加反向自检要求
- **数值 hover tooltip** —— StatePanel 的 hp / sanity / 各属性鼠标 hover 显示含义 + 阈值（12 项含大小写变体）
- **帮助 / 说明页 `/help`** —— SidebarNav 加入口，markdown 渲染 9 个章节：数值 / 检定 / NPC / 行动 / 隐性事件 / 快捷键 / 存档 / 标签字典 / FAQ
- **plot_event new_quest 去重** —— `<plot_event>` 描述与已有 active thread 相似度 ≥0.7（SequenceMatcher）时不新建（治图里 3 条几乎一样的「new_quest」）
- **GM prompt 铁律 22「关键信息推进义务」** —— PC 追问关键信息时本回合必须给实质答案，不可反复反问（≥2 次反问 = 失败）
- **GM prompt 铁律 23「世界状态前进」** —— 每回合 narrative 必须含外部世界变化（地点/新信息/NPC 出场/时间流动/物品）；禁止「思考-模糊-choices」原地循环

### 测试
- 后端 185 → 204（+19）；新文件 `test_name_repair.py`（9 个用例）
- 前端 build 通过；新组件 `HelpView.vue`

### API 变化
- `/health` 返回多一字段 `version: "0.12.0"`

---

## [v0.11] - 2026-04-30

**主题：角色卡 UI + PC 钩子驱动 + 数值锚定**

让 PC 的设定（能力/物品/弱点）和数值（属性/等级）真正影响跑团；NPC 信息按玩家「发现度」渐进揭示。

### 新增
- **PC 角色卡抽屉** —— GameView header 加「📜 角色卡」按钮，新组件 `CharacterCardDrawer.vue` 展示 PC 完整 profile + 当前数值 + 物品 + 基础属性 + XP 进度
- **NPC 渐进信息揭示**：
  - NPC 表加 `revealed_json TEXT default '{"name": true}'`，每字段一个 bool
  - GM 用 `<npc_update name="..." reveal="purpose,archetype"/>` 来揭示某些字段（玩家通过对话/调查触发）
  - NPC 创建时含值的字段自动 revealed=true（GM 写出来玩家就看到了）
  - **未揭示字段在 GM prompt 里隐藏值**，但用 `[未揭示：a/b/c]` 提示 GM 知道有可挖掘背景；让 GM 自然选择何时揭示
  - NpcDetailDialog 按 `revealed[field]` 渲染：未揭示显示 `**** （尚未通过对话/调查得知）`
- **PC 钩子驱动场景**（铁律 20）：
  - `_extract_pc_hooks` 从 profile_md 启发式抽取「能力/物品/弱点」三类（heading + 粗体 + key:value 三种 markdown 格式）
  - key_facts 注入「## PC 钩子（用上它们）」段
  - GM prompt 规定节奏：每 3-5 回合用上一项能力 / 物品在剧情节点起作用 / 每 5-8 回合触发弱点挑战
- **数值锚定**（铁律 21）：
  - key_facts 注入「## PC 当前数值」段（等级 + 自定义属性 + 物品列表）
  - GM prompt 规定 dice DC 表（属性 8-10 → DC 12；11-13 → 14；14-15 → 15；16+ → 17）
  - 物品必须在 narrative 显式引用 + 用完 emit `inventory_remove`
  - 等级影响 NPC 隐性态度
  - 升级时 narrative 描写气场变化

### 数据库
- NPC 表加列：`revealed_json`
- v0.11 迁移自动追加

### 测试
- 后端 172 → 185（+13）
- 前端 build 通过；新组件 `CharacterCardDrawer.vue`

### API 变化
- `GET /sessions/{id}/npcs` 返回每条 NPC 的 `revealed: dict[str, bool]` 字段（旧前端兜底：missing 时全部当 revealed）

---

## [v0.10] - 2026-04-30

**主题：实玩反馈统一优化（GM 输出质量 + UX）**

v0.9 实玩 11 条问题集中收口。覆盖标签解析容错、prompt 大改、隐性事件机制、speaker 区分、导出存档、关键 UX。

### 新增
- **`<say speaker="...">` / `<pc_action>` / `<hidden_event>` / `<scene_shift>` 4 个新标签** —— GM 现在按主体（旁白 / PC / 各 NPC）分别输出，前端按 speaker 分气泡渲染（左右气泡 + 居中旁白）
- **闭合标签错拼容错** —— `</narriative>`（多 i 拼写错）等编辑距离 ≤2 / 相似度 ≥70% 的错拼会自动当成正确标签关闭，不再吃掉后续 JSON
- **隐性事件系统（带引信）** —— GM emit `<hidden_event subject="..." consequence="N 回合不处理则 X"/>`，存到 `hidden_events` 表，每回合在 key_facts 里以「## 暗中状态(GM only)」段注入；玩家不可见，GM 必须按 consequence 演变化
- **PC 身份铁钉** —— `_build_key_facts` 顶部强制注入 `## PC 身份（最高优先级，永不可改）` 段，配合 prompt 铁律 16 治疗角色名漂移（沈三川 → 云野）
- **NPC 自动登记 NER 兜底** —— GM 漏 emit `<npc_update>` 时，启发式（频率 ≥2 的 hanzi token + cue 词 + 80 词停用表）自动建 stub
- **每回合事件持久化** —— `messages.events_json` 保存该回合所有非 narrative 标签结构化数据
- **每条 GM 消息事件详情 dialog** —— 气泡右下角 `🎲 N` 按钮，点击弹框按类型分组显示骰子/状态/NPC/任务等
- **存档导出** —— `GET /sessions/{id}/export?format=json|md`；SessionsView 每行加 📥 下拉菜单选 JSON / Markdown 下载
- **Enter 发送** —— 单 Enter 发，Shift+Enter 换行，IME composition 下不拦截

### Prompt 大改
铁律从 13 条扩到 19 条：
- 14：NPC 反应兜底 —— PC 任何搭话/提问/接近，本回合该 NPC 必须有反馈
- 15：玩家输入双视角解读（导演 vs 代入），都要给 NPC/环境反馈
- 16：PC 姓名锁
- 17：描写丰度 —— 200-400 字 / 必含 PC 后果 + NPC 细节 + 推剧情
- 18：首次提名必登记 —— narrative 提到新有名 NPC 必须紧跟 `<npc_update>`
- 19：输出顺序 —— narrative / pc_action / say 自然交错
- 新加「## 暗中状态机制」专节解释 hidden_event 用法
- few-shot example 重写为含 say / pc_action / hidden_event 的高质量样例

### 数据库
- 新表 `hidden_events`（id, session_id, subject, kind, severity, description, consequence, introduced_turn, status, resolution, resolved_turn）
- `messages` 加列：`events_json`、`parts_json`
- v0.10 迁移自动追加（PRAGMA + ALTER TABLE 幂等）

### 测试
- 后端 133 → 172（+39）
- 前端 build 通过；新组件：`SpeakerBubble.vue` / `MessageEventsDialog.vue`

### API 变化
- `GET /sessions/{id}/messages` 返回 message 多 `events: [...]` 字段
- `GET /sessions/{id}/hidden_events?include_resolved=false` 新端点
- `GET /sessions/{id}/export?format=json|md` 新端点

---

## [v0.9] - 2026-04-30

**主题：情绪系统 + GM 反应性**

让世界真的「在乎」玩家做的事——NPC 有情绪、PC 有心情、NPC 之间有关系，GM prompt 强制读取并按规则反应。

### 新增
- **NPC 5 轴情绪雷达**（anger / love / fear / respect / jealousy），`<npc_update>` 标签 emotion 字段累加并 clamp 到 0-100；NPC 详情页底部 5 行水平条可视化
- **PC 心情系统**：`<pc_mood>` GM 标签累加 PC 心情值；StatePanel 顶部徽章实时显示，流式更新（mirror `<state_change>` 模式）
- **NPC↔NPC 关系图**：`<npc_relation>` 标签 + `npc_relations` 表 + 新视图 `/play/:id/relations`（列表式，按 kind 分组），key_facts 注入下回合 prompt
- **GM 反应性原则** prompt 段落（4 节）：情绪 ≥70 必须主动表达、PC 心情同步场景描写、NPC 关系驱动剧情、PC 目标驱动 NPC 知情度
- **Playwright 端到端冒烟测试**：真实 FastAPI + 注入 stub model client 走完跑团 SSE 链路；防止 SSE/CRLF/CORS 类隐蔽 bug 回归
- **CI release artifact 冒烟检查**：DMG `hdiutil` 挂载验证 `dzmm.app` + `dzmm-backend` + `_internal/`；NSIS `7z l` 验证 `dzmm-backend.exe` + `python313.dll/_internal`，不通过 → 不发 release

### 数据库
- NPC 表加列：`emotion_json`
- Session 表加列：`pc_mood_json`
- 新表 `npc_relations`（按名字记录两个 NPC 之间的关系，避免级联问题）

### 测试
- 96 → 133（+37）后端测试
- 新增前端 `frontend/e2e/`：playwright.config.ts + smoke.spec.ts + mock_backend.py + test-server.ts
- 新增 GH workflow `.github/workflows/e2e.yml`：push/PR 触发 chromium 跑 e2e

---

## [v0.8] - 2026-04-29

**主题：编年史 + 目标系统 + 易用性**

### 新增
- 编年史页（`/play/:id/chronicle`）—— Timeline 数据可视化，按 Era 分章
- `<era_begin>` GM 标签 + Era 表 —— 标记剧情阶段切换
- PC 目标列表（StatePanel 新区块）+ `<pc_goal>` GM 标签
- 首次启动引导（4 步教程 + 欢迎页）
- Tauri 自动更新插件 + GitHub Releases 推送 `latest.json`

### 数据库
- 新表 `eras`、`pc_goals`
- 现有数据库自动迁移（迁移 helper 已有）

---

## [v0.7] - 2026-04-29

**主题：沉浸感增强 + 长线持续 + ACG 攻略向**

### 新增
- 任务日志页 `/play/:id/journal` —— 进行中 / 已解决 两栏分组
- **NPC 攻略详情**（点击 NPC 名打开）：
  - 多维好感（默认好感度 + GM 自定义轴：信任 / 羁绊 / 恋慕 / 敌意 ……）
  - 动机（purpose）、人设原型（archetype）字段
  - 完整互动时间线（notes_json 可视化）
  - 📌 钉住功能：核心 NPC 永不掉出 prompt context
  - GM 用 `<recall name="X"/>` 临时召回老 NPC，下回合自动注入完整档案
- NPC 浏览页 `/play/:id/npcs` —— 所有 NPC 卡片 + 搜索
- 角色立绘上传（5MB 上限，png/jpg/webp/svg/gif）+ GameView 头像显示
- 角色 XP / 升级系统：
  - GM 用 `<character_xp delta="N"/>` 给经验
  - POST /levelup 选属性 +1（HP/耐力 +5）
  - GameView 头部 XP 进度条；过阈值弹升级框
- 默认 BGM × 5 风格（dark/horror/healing/realistic/comedy） + SFX × 3（dice/state-up/state-down），ffmpeg 合成的 30s loop
- 4 张默认 SVG 立绘（Riku / 御坂雪 / 佐藤亚矢 / 沈三川）
- 静音按钮（🔊/🔇）右上角，localStorage 持久化
- GM 模型预热端点（POST /sessions/{id}/warmup）

### 性能
- 递归摘要压缩：摘要 > 3000 字时自动二次压缩，importance≥2 事件存到 `timeline` 表
- SSE 流式批处理（20 字 / 50ms 窗口）

### 数据库
- 新表：`timeline`
- NPC 表加列：`purpose`、`archetype`、`affinity_json`、`pinned`
- Session 表加列：`recall_pending_json`
- Character 表加列：`portrait_path`、`xp`、`level`
- 轻量迁移 helper（PRAGMA + ALTER TABLE，幂等）

### 测试
- 70 → 96（+26）

---

## [v0.6] - 2026-04-29

**Hotfix：Windows 中文用户名导致 `Failed to load Python DLL`**

### Fixed
- PyInstaller 切到 `--onedir` 模式：DLL 与 .exe 平铺，不再解压到 `%TEMP%`，根治中文 Windows `python313.dll` 加载失败
- `bundle.resources` 改 array 形式，保留 `_internal/` 子目录树（之前 object 形式会拍平）

### Performance
- macOS 冷启动 ~25s → ~3s（不再每次启动解压 19MB 单文件）

### Changed
- 移除 `tauri-plugin-shell` 依赖，改用 `std::process::Command` 直接 spawn
- 包体积 24MB → 23MB（.dmg 压缩后）

---

## [v0.5] - 2026-04-29

**playtest 痛点修复**

### Added
- Ollama `num_ctx=8192`（之前默认 2-4K，prompt 5-7K 被静默截断）
- GM system prompt few-shot 完整输出范例（教模型守标签格式）
- `DELETE /sessions/{id}/last_turn` 端点
- 跑团页「🔄 重新生成」、「✏️ 编辑上一动作」按钮
- 顶部状态栏显示 token 累计（in / out）
- 移动端响应式布局（侧栏 → 顶部 Tab，状态栏 → 抽屉）

### Performance
- SSE 旁路批处理：narrative 增量按 20 字 / 50ms 窗口攒发，前端 reactive 更新降 ~10x

---

## [v0.4] - 2026-04-29

**LAN/手机访问 + 跨平台打包**

### Added
- 启动欢迎对话框：「仅本机使用」/「启用手机访问」
- LAN 模式：后端 `0.0.0.0` + 同时通过 HTTP 服务前端 dist
- 顶部琥珀色横幅显示手机要打开的 URL（带复制按钮）
- 自动检测 / 启动 Ollama（macOS `open -a Ollama` / Windows `ollama serve`）
- `build_sidecar.py` 跨平台替代 `.sh`
- GitHub Actions 自动构建 release（macOS arm64 `.dmg` + Windows x64 `.exe` NSIS）
- `build_windows.ps1` 一键 Windows 本地构建脚本

### Changed
- Tauri 包目标改为 `["app", "dmg", "nsis"]`（移除 MSI，使用 NSIS .exe）

---

## [v0.3] - 2026-04-29

**plot_event + dice UI + polish**

### Added
- `<plot_event>` GM 标签 + `plot_threads` 表 + key_facts 注入下回合 prompt
- Standard 规则模式：d20 + DC 完整指令；StatePanel 显示最近骰点
- 推荐模型清单（README + UI 提示条）
- `/health` 端点 + 前端 BootGate 启动等待
- 后端日志轮转（`~/.dzmm/dzmm.log` 5MB × 3）

### Changed
- 前端代码分割：主包 1MB → 4kB（Element Plus 单独 chunk）

### Fixed
- `datetime.utcnow()` deprecation（127 个警告 → 0 个）

---

## [v0.2] - 2026-04-29

**鲁棒性 + CRUD + 原生打包**

### Added
- 无 `<narrative>` 标签时 graceful fallback（应对 deepseek-r1 等推理模型）
- GM prompt 末尾格式强化提示
- `PUT/DELETE` 端点：worlds、characters、model_configs（带级联保护）
- 前端编辑/删除 UI
- PyInstaller 后端打包 + Tauri sidecar 自动启动

### Tests
- 51 → 61

---

## [v0.1] - 2026-04-29

**首个可玩版本**

### Added
- FastAPI 后端 + SQLite 持久化 + 流式 SSE
- 流式 XML 标签解析器（`<narrative>` / `<state_change>` / `<npc_update>` / `<dice>` / `<choices>`）
- ModelClient 抽象 + Ollama 客户端 + OpenAI 兼容客户端（豆包/通义/DeepSeek/零一）
- GM system prompt 模板（世界观 + 角色 + 摘要 + 历史 + 行为铁律）
- 滚动剧情摘要器
- Vue3 + Vite + TypeScript + Element Plus + TailwindCSS 前端
- 5 个页面：模型 / 世界观 / 角色 / 跑团 / 跑团回合
- Tauri 桌面 shell（dev 模式）

### Tests
- 51 backend tests
