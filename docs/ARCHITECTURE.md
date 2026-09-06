# dzmm 架构

> 给新加入的开发者用的 onboarding 文档。覆盖目录约定、跑团一回合的数据流、关键设计模式。

> **cutover 提示（2026-09）**：产品已统一为单一 DZMM（ADR-010/011）。当前唯一产品树是
> `backend/`（FastAPI schema v3 + 命令引擎）、`desktop/`（Tauri/Vue）、`mobile/`（Flutter）、
> `contracts/`、`eval/`、`packaging/`。本文档其余章节描述的是 cutover 前的旧版架构，
> 仅作历史参考，待按新结构重写；新结构入口见 `README.md` 与 `docs/ACTIVE_DELIVERY_INDEX.md`。

## 顶层结构（当前）

```
dzmm/
├── backend/           Python FastAPI host（schema v3 + Alembic + 命令引擎）
│   ├── src/dzmm/      源码（transport-neutral core + FastAPI 薄壳）
│   ├── tests/         pytest（169+）
│   └── pyproject.toml
├── desktop/           Tauri/Vue 桌面 Local Host（macOS/Windows）
│   ├── src/           Vue 3 + Vite
│   └── src-tauri/     Rust 壳 + backend-runtime sidecar
├── mobile/            Flutter Android Local Host（内嵌 Python 核心）
├── contracts/         版本化 JSON Schema（体验契约）
├── eval/              evidence-first 成熟度评分与 phase 证据
├── packaging/         PyInstaller sidecar 构建
├── docs/              ADR / 计划 / 评审 / 交付索引
├── .github/workflows/ release.yml + backend-ci.yml + e2e.yml
├── CHANGELOG.md
└── README.md
```

## 顶层结构（cutover 前，历史）

```
dzmm/
├── backend/           Python FastAPI + SQLite + LLM 适配器
│   ├── src/dzmm/      源码
│   ├── tests/         pytest 测试（346+）
│   ├── pyproject.toml
│   └── dzmm-backend.spec  PyInstaller --onedir spec
├── frontend/          Vue 3 + Vite + Element Plus + Pinia
│   ├── src/           源码
│   ├── e2e/           Playwright SSE smoke
│   └── src-tauri/     Rust 桌面壳（Tauri 2）
├── packaging/         一键打包入口（PyInstaller + Tauri）
│   ├── build.py       跨平台 orchestrator
│   ├── build.ps1      Windows PowerShell wrapper
│   └── dist/          打好的 .dmg / setup.exe（gitignored）
├── docs/superpowers/plans/  实现计划（含 archive/ 老版本）
├── .github/workflows/ release.yml + e2e.yml
├── CHANGELOG.md
└── README.md
```

## 后端目录约定

```
backend/src/dzmm/
├── api/             HTTP 路由（FastAPI APIRouter）
│   ├── routes_sessions/       跑团核心（拆分为独立模块）
│   │   ├── __init__.py        汇总注册所有子路由
│   │   ├── _common.py         共用依赖（session_maker 注入）
│   │   ├── base.py            Session CRUD + 列表
│   │   ├── turn.py            POST /turn — SSE 游戏循环
│   │   ├── npc_tick.py        POST /npc_tick — NPC 主动行动（v0.2.7）
│   │   ├── npcs.py            NPC CRUD + 好感 / 情绪
│   │   ├── messages.py        消息历史
│   │   ├── threads.py         剧情线
│   │   ├── goals.py           PC 目标
│   │   ├── hidden_events.py   暗中状态
│   │   ├── locations.py       场景 / 位置
│   │   ├── export.py          JSON / Markdown 导出
│   │   ├── feedback.py        玩家反馈
│   │   ├── suggest.py         上下文行动建议（v0.2.5）
│   │   └── spinoff.py         续作创建
│   ├── routes_screenplay.py   剧本驱动：generate / mark_decision / continue ...
│   ├── routes_worlds.py       世界观 CRUD
│   ├── routes_characters.py   角色 CRUD + portrait 上传
│   ├── routes_models.py       模型配置 CRUD（ollama / lm_studio / openai_compat）
│   ├── routes_wizard.py       向导式创建（6 步 LLM 引导）
│   ├── routes_system.py       /health / /system/status / /system/ollama/start
│   └── schemas.py             Pydantic in/out 模型
├── db/
│   ├── models.py    SQLAlchemy ORM（World / Character / Session / Message / NPC /
│   │                NpcRelation / PlotThread / Era / Timeline / CharState /
│   │                StorySummary / PCGoal / HiddenEvent / Screenplay /
│   │                ScreenplayRevision / Feedback）
│   │                NPC 新增 last_initiative_turn 字段（v0.2.7）
│   └── base.py      engine / session_maker + 增量 column 迁移（_V07 - _V027）
├── models/          LLM 适配器（不是 ORM 而是 model client）
│   ├── client.py    抽象基类 ModelClient + StreamChunk 类型
│   ├── ollama.py    Ollama HTTP 流式
│   ├── openai_compat.py  OpenAI 兼容（可空 api_key 兼容 LM Studio）
│   └── factory.py   build_client(cfg) 分发
├── parsing/
│   ├── stream_parser.py  增量 XML 标签解析（narrative / say / pc_action /
│   │                     state_change / npc_update / dice / choices ...）
│   ├── repair.py    错拼闭合标签容错
│   └── events.py    NarrativeDelta / TagComplete / ParseError 数据类
├── prompts/
│   ├── gm_template.py     25+ 行为铁律 + 反应性原则 + 暗中状态 + few_shot
│   │                      v0.2.7：铁律 16 强化感官细节 + NPC 对白要求
│   ├── gm_few_shot.py     示范 1-4（含 v0.2.7 场景/NPC 管理示范）
│   ├── outliner_template.py 剧本生成 prompt（输出 JSON schema）
│   ├── summarizer_template.py 摘要器 prompt（递归压缩）
│   └── wizard_prompts.py  向导 6 步 prompt
├── service/         业务逻辑（无 HTTP / DB session 直接耦合）
│   ├── game.py      run_turn() 主循环 + key_facts 注入 + name repair
│   │                v0.2.7：首回合自动调 _auto_generate_screenplay()
│   │                v0.2.7：每回合末 find_initiative_npc() + npc_initiative 标签
│   ├── npc_initiative.py  NPC 主动行为资格判断（v0.2.7）
│   │                      find_initiative_npc(session, session_id, turn) -> NPC|None
│   │                      条件：last_seen > 0 + 闲置 ≥2 回合 + 冷却 ≥4 回合 + eagerness > 0
│   ├── state_apply/       标签应用拆分为多文件（v0.2.6+）
│   │   └── *.py           每类标签一个处理模块
│   ├── screenplay.py      剧本生成 + 续作
│   ├── summarizer.py      超长会话摘要
│   ├── activity_log.py    活跃度记录
│   ├── name_repair.py     NPC 姓名漂移修复
│   ├── npc_dossier.py     NPC 档案汇总
│   └── wizard.py          向导步骤执行
├── seed_data.py     首次启动预设：4 个世界 + 4 角色 + 默认模型配置
├── secrets.py       OS keychain 集成（API key 不入库）
├── config.py        APP_DIR、DEFAULT_DB_URL、host/port env 解析
├── logging_config.py  ~/.dzmm/dzmm.log 5MB×3 rotation
├── main.py          FastAPI 应用工厂 create_app + build_default_app
└── __init__.py      __version__
```

## 前端目录约定

```
frontend/src/
├── api/             HTTP 客户端 + TS 类型
│   ├── client.ts    axios + baseURL 解析（Tauri / dev / LAN 三模式）+ fetchHealth
│   ├── sessions.ts  session 全部 API + 类型（HiddenEventItem / FeedbackItem 等）
│   │                v0.2.7：新增 npcTick() 方法
│   ├── screenplay.ts 剧本 API + KNOWN_GENRES
│   ├── worlds.ts / characters.ts / models.ts
│   └── types.ts     共享类型（GameSession / SessionIn / Character ...）
├── components/      可复用 UI
│   ├── BootGate.vue        启动门 + 启动日志面板
│   ├── SidebarNav.vue      左侧栏 + 调试模式 watermark + 设置入口
│   ├── StatePanel.vue      右侧状态面板（数值 tooltip）
│   ├── SpeakerBubble.vue   按 speaker 分气泡
│   ├── CharacterCardDrawer.vue  PC 角色卡抽屉
│   ├── NpcDetailDialog.vue  NPC 详情（reveal 字段渲染 ****）
│   ├── MessageEventsDialog.vue 单回合事件列表
│   ├── FeedbackDialog.vue
│   ├── GenreSelector.vue   剧本类型选择
│   ├── LevelUpDialog.vue
│   ├── OnboardingTour.vue  首次启动 4 分钟引导
│   ├── CharacterAvatar.vue
│   └── MarkdownView.vue
├── composables/
│   ├── useGameTurn.ts    游戏回合控制 + tag 分发（v0.2.7：npc_initiative 事件处理）
│   ├── useTurnStream.ts  SSE 流式订阅
│   ├── useAudio.ts       BGM + SFX
│   └── useUpdater.ts     Tauri auto-updater
├── stores/          Pinia
│   ├── app.ts            isTauri / lanMode / lanUrl / tourStep
│   ├── sessions.ts / worlds.ts / characters.ts / modelConfigs.ts
│   └── debug.ts          Konami 序列 + localStorage 持久
├── views/           路由级页面
│   ├── LayoutView.vue    SidebarNav + router-view
│   ├── WelcomeView.vue   首次启动欢迎
│   ├── SessionsView.vue  存档列表 + 创建（向导/快速）+ 导出 + 续作 + 删除（含角色卡）
│   ├── SessionGenerateView.vue  剧本生成 loading 页
│   ├── GameView.vue      跑团主界面（v0.2.7：NPC initiative banner + 4s 倒计时触发）
│   ├── ScreenplayView.vue  剧本进度
│   ├── WorldsView.vue / CharactersView.vue / ModelsView.vue
│   ├── JournalView.vue / NpcsView.vue / RelationsView.vue / ChronicleView.vue
│   ├── HelpView.vue      说明页
│   ├── SettingsView.vue  检查更新 + 重新引导
│   └── DebugView.vue     调试模式集中页（剧透剧本 / hidden_events / NPC 全字段）
├── router/index.ts  hash mode + 首次启动重定向 /welcome
├── App.vue          BootGate 包裹 router-view + Konami 全局监听
├── main.ts          Vue + Pinia + ElementPlus 挂载
└── env.d.ts         __APP_VERSION__ 全局常量声明
```

## 跑团一回合的数据流

```
玩家发送动作（前端 GameView）
  ↓ POST /sessions/{id}/turn  Server-Sent Events
service.game.run_turn(session, sess_id, user_action, client)
  │
  ├─ Message(role="user").persist  把玩家这条消息存表
  ├─ _build_key_facts(session, sess_id, current_turn, character)
  │     ↓ 查 NPC（pinned + 最近 last_seen + recall_pending）
  │     ↓ 查 plot_threads（active）+ pc_goals + npc_relations
  │     ↓ 查 hidden_events（active）→「暗中状态(GM only)」段
  │     ↓ 查 screenplay（active）→「当前剧本进度」段
  │     ↓ 算 PC 钩子（profile_md 抽 abilities/items/weaknesses）
  │     ↓ 拼成纯文本 key_facts 段
  ├─ [首回合] _auto_generate_screenplay()  异步调 outliner LLM 生成剧本大纲
  │     ↓ 根据 world.style 映射 genre → build_outliner_messages()
  │     ↓ 流式 LLM → 剥 markdown fence → 解析 JSON → 存 Screenplay 表
  │     ↓ session.flush() 确保同 tx 内 _build_key_facts 能读到
  ├─ build_gm_messages(world, character, story_summary, key_facts, recent, action)
  │     ↓ 拼 25+ 铁律 + 反应性 + 暗中状态机制 + 标签字典 + few_shot
  │     ↓ 末尾追加 _load_recent_messages(12 条)
  │     ↓ 末尾追加 user action
  └─ ModelClient.stream(messages, params)  调 Ollama / LM Studio / OpenAI
       ↓ 每 chunk
     parsing.stream_parser.feed(chunk) 增量解析
       ├─ NarrativeDelta(text) → 立即转 SSE 给前端 narrative 事件（玩家看到的流式文字）
       └─ TagComplete(name, attrs, content) → 累积到回合末
       ↓ 流结束
     state_apply.apply_tags(session, sess_id, all_tags, turn, narrative_text)
       ├─ state_change → CharState.stats_json / inventory_json 更新
       ├─ npc_update → NPC upsert + reveal mask + emotion 累加 + auto-create stub
       ├─ npc_relation → npc_relations 表去重 upsert
       ├─ plot_event → plot_threads insert（new_quest / hook_introduced 去重）
       ├─ era_begin → eras 表 + 推进 timeline 起点
       ├─ character_xp → Character.xp 累加
       ├─ pc_goal type=add/complete → pc_goals 状态变更
       ├─ pc_mood → Session.pc_mood_json 累加 clamp
       ├─ hidden_event → hidden_events 创建 / resolve
       ├─ chapter_advance / event_complete / plot_turn / ending → screenplay 进度
       ├─ recall name="X" → Session.recall_pending_json 待下回合 prompt 重注入
       └─ name_repair：扫 GM 输出修「我叫/我是」漂移
     Message(role="assistant", events_json=[all_tags]).persist
     Session.turn_count += 1 + tokens 累计
     超过 10 回合：summarizer.maybe_summarize 递归压缩
     [v0.2.7] find_initiative_npc() 检查资格
       ↓ 有资格 NPC → yield TagComplete(name="npc_initiative", attrs={"npc": name})
       ↓ 前端接收 → 4s 倒计时 banner → 自动 POST /npc_tick

NPC 主动行动（POST /sessions/{id}/npc_tick）
  ↓ 构造特殊动作字符串：「【NPC主动行动】{npc_name} 主动找到了 PC...」
  └─ 复用 run_turn() 完整流程（同样 SSE 流式）
```

## NPC 主动行为机制（v0.2.7）

每回合结束后，`find_initiative_npc()` 检查所有 NPC 的资格：

| 条件 | 说明 |
|---|---|
| `last_seen_turn > 0` | NPC 必须已在场景中出现过 |
| 闲置 ≥ 2 回合 | `current_turn - last_seen_turn >= 2` |
| 冷却 ≥ 4 回合 | `current_turn - last_initiative_turn >= 4` |
| `eagerness > 0` | 热情值 = pinned(+10) + favor//5 + max(emotion)//10 |

满足条件的 NPC 中热情值最高者胜出。后端发出 `npc_initiative` SSE 标签，前端显示 4 秒倒计时横幅，超时自动触发 `/npc_tick` 端点（玩家也可手动忽略）。

## 数据库 schema 概览

按生命周期归类：

**全局（多 session 共享）**
- `worlds` — 世界观（name / content_md / rules_json / style）
- `characters` — PC 角色卡（name / profile_md / base_stats / xp / level / portrait_path）
- `model_configs` — LLM 配置（ollama / lm_studio / openai_compat）

**Session 主表**
- `sessions` — 一局跑团（world_id / character_id / gm_model_config_id / turn_count / pc_mood_json / recall_pending_json）

**Per-session 数据（`DELETE /sessions/{id}` 全部 cascade）**
- `messages` — user + assistant 历史（events_json 含解析后的标签）
- `char_states` — 实时 stats / inventory（按 session_id PK）
- `story_summaries` — 摘要器输出（按 session_id PK）
- `npcs` — 该 session 的 NPC 表（含 emotion_json / affinity_json / revealed_json / last_initiative_turn）
- `npc_relations` — NPC 之间关系
- `plot_threads` — 剧情线（new_quest / hook_introduced / major_event / ...）
- `eras` — 章节 / 编年史
- `timeline` — 长线关键事件（recursive summary 提取）
- `pc_goals` — 玩家目标
- `hidden_events` — 暗中状态（GM 后台引信）
- `screenplays` + `screenplay_revisions` — 剧本驱动
- `feedbacks` — 玩家应用内反馈

## 关键设计模式

### 1. LLM 输出结构化标签 → 状态机更新 → 下回合注入
GM 不直接修改 DB——它在自然语言旁白中夹带 `<state_change>`、`<npc_update>` 等标签。后端 `stream_parser` 增量解析、`state_apply` 应用到 DB。下回合 `_build_key_facts` 把 DB 当前状态拼回 prompt。这条闭环是整个游戏的核心。

### 2. 渐进式 NPC 信息揭示
`NPC.revealed_json: dict[field, bool]`。GM emit `<npc_update reveal="purpose,archetype">` 揭示。`_build_key_facts` 注入 prompt 时**未揭示字段不输出值**只输出占位提示，避免 GM 误说。前端 NpcDetailDialog 渲染未揭示字段为 `****`。

### 3. 隐性事件后台演变
`<hidden_event subject="小菱" kind="injury" consequence="5 回合不治会昏迷"/>`。每回合在 prompt 里以「## 暗中状态(GM only)」段注入，玩家不可见但 GM 必须按 consequence 演变化。

### 4. 剧本驱动跑团
开档首回合自动调 outliner LLM 生成结构化大纲（章节 / 主要 NPC / 关键事件 / 完结条件）。每回合 prompt 注入「## 当前剧本进度」段。GM emit `<event_complete>` 推进、`<chapter_advance/>` 切章、`<ending/>` 完结。

### 5. NPC 主动行为（v0.2.7）
每回合后台计算 NPC 热情值，符合条件者触发 `npc_initiative` SSE 信号 → 前端 4 秒倒计时 → 自动注入 NPC 主动互动回合。无需玩家输入，让世界保持生命力。复用 `run_turn()` 保持完整状态更新链路。

### 6. SSE 内 HTTPException 陷阱
在已发送 HTTP 200 响应头之后，async generator 内的 `raise HTTPException(404)` 会静默关闭流，而非返回 HTTP 错误码。正确做法是 in-band 错误事件：`yield {"event": "error", "data": json.dumps({"message": "..."})}; return`。

### 7. 启动日志
Tauri Rust 端 `spawn_backend` 用 `Stdio::piped()` 捕获 PyInstaller binary 的 stdout/stderr，emit `backend-log` 事件给 webview。前端 `BootGate` 把事件 + 自身状态变化都收到 timestamped 日志面板，便于诊断 Windows / 路径 / 权限等启动失败。

### 8. 调试模式
Konami 序列 `↑↑↓↓←→←→` 全局触发，`/debug` 页展示一切被 reveal mask / 剧本剧透限制 / 普通 UI 隐藏的数据。

## 前端运行模式

`api/client.ts:deriveBaseURL()` 根据 `window.location.hostname` 选 baseURL：
- Tauri webview（`tauri.localhost`）→ `http://localhost:8765`
- 浏览器开发（`localhost` / `127.0.0.1`）→ `http://localhost:8765`（Vite dev 不 proxy SSE，直连后端避免 buffering）
- 同 WiFi 手机（任意 IP）→ `http://<host>:8765`

要让 LAN 模式工作，后端必须 bind `0.0.0.0`（Tauri shell 的 `start_backend(lanMode=true)` 设环境变量 `DZMM_HOST=0.0.0.0`）。

## 打包

```bash
python packaging/build.py
```

依次：检查 prereqs → backend venv + pip install → npm install → `backend/build_sidecar.py` 跑 PyInstaller `--onedir` → `npm run tauri:build` → 把产物拷到 `packaging/dist/`。

CI（`.github/workflows/release.yml`）在推 `v*` tag 时自动跑 macOS DMG + Windows NSIS，含 artifact smoke check。

## 测试

- 后端：`pytest`，346+ 用例覆盖 parser / state_apply / game / api / prompts / models / secrets / npc_initiative
- 前端：`npm run build` 跑 vue-tsc 类型检查
- E2E：`.github/workflows/e2e.yml` 在 Ubuntu 跑 Playwright chromium，启 mock_backend.py（注入 stub LLM）+ Vite dev → 自动测开档创建 → SSE 跑团 → narrative 显示

E2E 用 stub model：当 system prompt 含「TRPG 编剧」（outliner 标记）→ 返回固定 JSON 大纲；其它（GM 调用）→ 返回 `<narrative>...</narrative>` 跑团片段。
