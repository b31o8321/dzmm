# 更新日志

按 [Keep a Changelog](https://keepachangelog.com/) 风格，版本对应 git tag。

## [v0.15.0] - 2026-05-17

**机械引擎重构：Python-first，LLM 只描述**

v0.10-v0.14 把 LLM 当全能 GM 用，让它同时管叙事 + 算骰子 + 算伤害 + 判技能成败。问题：LLM 不会均匀随机（playtest 见过连续 8 次 d20=9）、算术不稳定、伤害数字凭感觉。v0.15 把"数字判断"全部抽到 Python 引擎，LLM 只输出意图，Python 解析、计算、写回 key_facts。

### 新引擎层 `dzmm.engine`

- **`engine.schema`** —— `StatBlock`(6 属性 3-18)、`Skill`、`Item`(name/qty/type/effects)、`ItemEffect`(10 种类型) Pydantic 模型 + safe-fallback 解析器
- **`engine.dice`** —— `roll(formula)` 支持 d20/2d6+3/d100 标准记号；`skill_check(attr, skill_lvl, dc)` = `d20 + (attr-10)//2 + skill_lvl//10 vs DC`；nat 20 大成功 / nat 1 大失败；可注入 seeded RNG
- **`engine.character`** —— 加载/写入 StatBlock、skills、inventory；`apply_vital_delta` 自动 clamp HP/Sanity/Stamina 到 [0, max]
- **`engine.items`** —— `resolve_use_item` 应用 heal_hp / heal_sanity / heal_stamina 效果，消耗品 qty 减 1 或移除
- **`engine.combat`** —— `resolve_attack` 全流程（攻击命中、伤害骰、击败判定）；`roll_initiative`；STR/DEX 攻击属性自动选择；AC = 10 + DEX_mod + 护甲
- **`engine.predicates`** —— 6 种结构化谓词（location_reached / npc_state / stat_threshold / item_owned / faction_tension / combined any-all）+ async `evaluate`
- **`engine.genre_templates`** —— 5 个 genre 的属性/技能/起始装备模板，wizard 创建角色时按 genre 套用

### DB 迁移

- **V050** —— Character 加 6 属性 + max_hp/sanity/stamina + skills_json + inventory_json + equipment_json；NPC 加 stat_block_json；CharState 加 stamina；Session 加 ruleset_version
- **V051** —— Session 加 pending_resolutions_json（机械结算队列）
- **V052** —— Session 加 combat_order_json（先攻顺序）
- 旧 free-form `base_stats_json` 字段保留兼容，新 schema 优先

### 新标签

- `<dice_request formula="2d6+3" purpose="伤害"/>` —— GM 请 Python 摇骰
- `<skill_request skill="潜行" attribute="dexterity" dc="14"/>` —— 技能检定
- `<item_use item_name="治疗药水" actor="PC"/>` —— 玩家用物品
- `<attack attacker_kind="pc" attacker_id=3 target_kind="npc" target_id=5 weapon="短剑"/>` —— 单次攻击
- `<initiative_request combatants="PC,goblin_1,goblin_2"/>` —— 战斗开始排序

每个标签 Python 解析后写一条 record 到 `Session.pending_resolutions_json`，下回合 `_build_key_facts` 注入「## 上回合机械结算」段告诉 GM 数字结果，GM 据此叙述。

### 事件谓词自动触发

- WorldEvent.trigger_conditions_json 现在可以是结构化谓词，每回合 `event_evaluator.check_and_trigger_events` 自动评估命中即 emit `event_trigger`
- 旧 free-text 谓词解析为 inert，永不自动触发（仍可由 GM 手动 emit）
- run_turn 在 `apply_tags` 之后自动调评估器（仅在 sess.framework_id 不为空时）

### Genre 驱动的角色初始化

- 5 个 canonical genre 的起始属性 / 技能 / 物品模板（悬疑探案 INT 高 + 侦探笔记本；英雄成长 STR 高 + 剑甲；政治阴谋 CHA 高 + 文件信物；灾难求生 CON 高 + 医疗包；恋爱攻略 CHA 高 + 礼物香水）
- 可选 ±2 jitter（seeded rng 保证可复现）
- wizard `generate_character` 接收 genre 参数；finalize 时把结构化 stat_block/skills/inventory 持久化到 Character 行

### Prompt 改造

- gm_template.py 新增「机械结算 (v0.15)」段：GM 改输出 intent，不再自己算数字；战斗段教 GM 用 initiative_request + attack
- gm_few_shot.py 加 3 个 few-shot（skill_request / item_use / 完整战斗回合）
- scene_v2_template.py 同步机械结算说明

### 前端 StatePanel 全面重写

- HP / Sanity / Stamina 进度条（红/紫/黄）
- 6 属性网格 + modifier 显示（top 2 高亮）
- 技能条按等级降序，超过 5 个折叠
- 装备槽（武器 / 护甲 / 饰品）
- 物品按类型分组 + 效果 chip + el-tooltip 详情
- 近期机械结算 feed（dice / skill / attack / initiative / item 各种 emoji 前缀）
- 战斗中显示 Combat HUD（先攻顺序 + 结束战斗按钮）
- 老存档无 v0.15 数据时 fallback 到 legacy stats/inventory 显示

### state 接口扩展

`GET /sessions/{id}/state` 现在额外返回 attributes / vitals / skills / inventory_v2 / equipment / combat_order / recent_resolutions（旧字段 stats / inventory / npcs 不变，向后兼容）

### 测试

- v0.15 6 个 batch 累计 +159 后端测试（749→788 减去重叠 = 净 +35 跨 batch；其实是 70+22+28+35+4）
- 全套 788 passed / 1 skipped，0 回归

### 后续

- Phase D（QLoRA 微调）：仍待硬件
- 战斗 UI 交互（点 NPC 攻击、装备点击换装）：留作下一个迭代
- 物品商店 / NPC 物品交换：未来

---

## [v0.14.0] - 2026-05-17

**剧本驱动打磨包 + 死代码大清扫**

v0.14 设计文档（2026-04-30 写的）大部分功能其实已经在 v0.7-v0.11 各版本里散落实现了：剧本大纲生成、`<plot_turn>` 异步重写、`<ending/>` 完结、续作 / 续写下一章、Genre 模板。这一版把缺失的体验拼图补齐，并清理积累的死代码。

### 新增

#### ✏️ 大纲手动编辑（P2）
- **`PATCH /sessions/{id}/screenplay`** —— 接受 `chapters` / `main_characters` / `ending_md` / `opening_hook` 任意子集，仅更新提供的字段。
- 每次成功 PATCH 自动写一条 `ScreenplayRevision`（trigger_description="manual_edit"），手动编辑与 LLM 重写在同一 revisions 视图里可见。
- **ScreenplayView 加「✏️ 编辑大纲」按钮** —— 四 tab 对话框（开场 / 章节 / 主要 NPC / 结局）。章节和 NPC 列表用 JSON textarea（v1，后续可上结构化编辑器）；前端 JSON 解析失败 → 阻止提交 + warning。
- 6 个新测试覆盖 PATCH 流程。

#### 📚 Genre 模板真正结构化（P5）
- `KNOWN_GENRES` 从 `dict[str, str]` 升级为 `dict[str, dict]`，每个 genre 含 `desc` / `act_count` / `ending_archetype` / `required_roles`。
- 悬疑探案(3) / 英雄成长(5) / 政治阴谋(4) / 灾难求生(4) / 恋爱攻略(3) 各自的章数 + 典型结局 + 建议 NPC 原型注入 outliner & rewrite prompt。
- 前端 `GenreSpec` 类型完全对应；WizardView 复用现有字段不破坏。
- 3 个新测试。

#### 🎭 剧本面板与开放世界并存（P1）
- ScreenplayProgressPanel 不再 v-else 排他于框架模式；剧本 tab 与「世界地图」「主线进度」并存。
- 默认 activeTab：仅框架 → 'map'；仅剧本 → 'screenplay'；两者共存 → 'map' + 剧本 tab 可切换。

#### 🔀 续作 vs 续写下一章 区分（P4）
- SessionsView「+ 续作」按钮 (spinoff = 新存档) 现在仅在源剧本 `status="concluded"` 时启用；未完结时禁用并 tooltip 指向游戏内「📖 续写下一章」(continue = 当前存档新增章)。
- 利用 StandaloneScreenplay 已有的 `status` 字段，零后端改动。

### 测试

- **plot_turn → rewrite_in_background 集成测试**（P3）—— 之前最脆弱的胶水代码无端到端测试。+3 测试覆盖正常路径、outliner 失败 fallback、连续两次重大转折的串行化。
- 后端测试总数：617 → 629（+12）。

### 清理

#### 删除死代码（−516 LoC）
- 前端：`GenreSelector.vue`（无导入）、`SessionGenerateView.vue` + 路由项（孤儿 view）、`api/wizard.ts` 中 `worldDetails/character/npcs/screenplay` 四个 wrapper、`api/screenplays.ts` 中 `listAll/get/update` 三个 wrapper。
- 后端：`prompts/director_template.py`（被 director_v2/open_world 取代）、`prompts/npc_react_template.py`（被 npc_actor 取代）、`prompts/rules_template.py`（已并入 gm_template）。

#### 文档归档
- `docs/superpowers/plans/` 下 26 个 2026-04-30 ~ 2026-05-10 的旧计划文档移到 `archive/`，活动目录只保留当前 roadmap。

### 状态

项目从 v0.10.3「暂停」状态完整重启，连续完成 v0.11.0 + v0.14.0 两个里程碑。Phase A/B/C/v0.11/v0.14 全部已实现，剩余：Phase D（QLoRA 微调，需硬件 + 数据集积累）。

---

## [v0.11.0] - 2026-05-17

**开放世界运行时打通 + Phase C 评测数据导出**

v0.10.x 把开放世界 wizard、表结构、Director 选型框架合入了，但运行时是断的——前端面板永远空白、事件状态机不写入、Director 触发器只懂剧本模式。v0.11.0 把这条链跑通，并补完 Phase C 自动评测的 Phase D 数据导出。

### 新增

#### 🌐 开放世界运行时数据流（v0.11 Batch 1）
- **`GET /sessions/{id}/world_state`** —— 单接口聚合返回 locations / factions / npcs / events / pc_location_id / campaign。joins WorldXxx 模板和 SessionXxxState 覆盖层；未揭示 NPC + 未触发事件对玩家隐藏。
- **GameView onMounted 拉取 + 每回合刷新** —— WorldMapPanel / CampaignProgressPanel 不再永远空白。
- **WorldMapPanel SVG 拓扑视图** —— 力导向布局（150 ticks Coulomb + Hooke），地点为节点、connections 为边。状态色环、PC 当前位置高亮、未探索置灰。`地图 / 列表` Tab 切换。
- 测试：+6 (test_world_state.py)

#### 🎯 事件状态机 + Campaign Phase 推进（v0.11 Batch 2）
- **`<event_trigger event_id="N"/>` 解析器支持** —— KNOWN_TAGS 加入；state_apply 写入 SessionEventState.status="triggered"。
- **`<event_complete event_id="N"/>` 开放世界路径** —— attrs 里有 event_id 时走开放世界逻辑（写 SessionEventState.status="completed"），有 chapter+event 时仍走剧本逻辑，两条路径互斥共存。
- **`_apply_phase_advance`** —— event_complete 后追加到 SessionCampaignState.triggered_key_events_json；按前置阶段 DAG 重算 current_phase_id。
- **Orchestrator 转发** —— Director 输出里的 event_trigger / event_complete 标签提前 yield 给 apply_tags，保证 Scene 运行前事件状态已就绪。
- **director_open_world_template** —— `_SYSTEM` 加上 trigger→complete 生命周期说明。
- 测试：+12 (test_world_state_machine.py)

#### 🚦 Director 触发器认知开放世界（v0.11 Batch 3）
- **5 个新触发条件** —— event_completed / event_triggered / phase_advanced / faction_tension_breached / proactive_npc_pending 任一发生立刻触发 Director。
- **framework 模式 interval 缩短** —— DIRECTOR_INTERVAL_TURNS_FRAMEWORK = 3（vs 剧本模式 5），开放世界 Director 重新规划更频繁。
- **`_build_director_trigger_state` 框架字段** —— 当 `sess.framework_id` 为真时计算 5 个新字段，否则全 False（不查询节省成本）。
- 测试：+12 (test_triggers_framework.py)

#### 🧙 开放世界向导命名收齐 + finalize 完整链
- **`/wizard/fw/character`** —— 新增端点与 `/wizard/character` 共享 `_fw_character_impl()` 助手；老端点带 @deprecated 标记保留兼容；前端 OpenWorldWizardView 切到新端点。
- v0.10.3 已包含的 wizard finalize 链式调用（framework → world → character → session → /play）继续生效。

#### 📊 Phase C 评测 JSONL 数据导出（Phase D 准备）
- **`dzmm.eval.export.export_jsonl`** —— 把通过分数阈值的回合导出为 JSONL（每行一个 (messages, completion, score) 训练记录）。
- **CLI `--export-jsonl PATH --min-score 7.0`** —— 评测结束后自动生成训练数据。
- **debug_mode 自动捕获** —— 评测期间 settings.debug_mode 必须开启，否则 prompt_json 为空、该回合跳过并 warning。
- 测试：覆盖阈值过滤 / 缺失 prompt_json / JSONL 结构 / Unicode 保留。

### 文档

- README 状态从「暂停更新 v0.10.3」改回「开发中 v0.11.0」；标记 Phase C 已实现；后续规划保留 Phase D + v0.14。
- 学习文档 langchain-rag.md / langgraph-multiagent.md / agent-eval.md 体现 Phase A/B/C 全部已上线。

### 修复（沿用 v0.10.x 累计）

- v0.10.3 的 wizard finalize / 调试链路弹窗 / Windows ChromaDB rmtree / e2e localStorage key / 调试链路 `immediate: true` watcher 等修复全部包含。

### 统计

- 30 新测试（v0.11 Batch 1/2/3）+ JSONL export 新测试 + 2 wizard 新测试。
- 后端 600+ 测试全绿（v0.10.1 → v0.11.0：~530 → 630+）。

---

## [v0.10.3] - 2026-05-17

**项目暂停前的 bug 修复打包 + 开放世界向导完整链**

v0.10.2 之后陆续修了几个关键 bug，统一以 v0.10.3 收尾。这也是项目正式暂停前的最终版本。

### 修复

- **开放世界向导 finalize 完整链**（`5f3294d`）—— 之前向导走完只创建 WorldFramework，不创建 World/Character/Session，提示成功后跳到 sessions 列表玩家看不到任何新内容；现在完整链式调用 framework → world → character → session，直接进入游戏页面。
- **调试链路弹窗空白**（`3300cef`）—— `TurnDebugChainDialog` 的 `watch` 没设 `immediate: true`，组件 mount 时 `modelValue` 已经是 `true`，watcher 监听不到变化所以不调 API，弹窗永远空白。
- **Windows ChromaDB rmtree 失败**（`921287c`）—— `delete_world_index` 先创建 `PersistentClient` 才删目录，Windows 上 sqlite 文件被锁导致 `rmtree` 报 PermissionError；改成直接删目录跳过 chromadb 客户端。
- **E2E smoke CI 多次失败**（`0305737` / `e51e798` / `5c72961` / `fcb6e3a`）—— localStorage key 写错、`isVisible` 不会等待、mock backend 没 stub Ollama 检查、新建存档表单字段调整（剧本字段替代角色字段）。
- **向导卡片网格 UI**（`63b51bd`）—— 步骤 2-5 的列表项换成卡片网格，告别难看的项目符号列表。

### 文档

- **后端全文中文注释**（`f2adde2`）—— 50+ Python 文件加上面向「只懂 Python 语法、不懂 FastAPI/SQLAlchemy/架构」初学者的中文注释
- **代码阅读路径文档**（`e89ff1f`）—— `docs/learning/code-reading-path.md`，7 阶段分步学习路线
- **README 增加学习文档章节 + 后续规划章节**（`1c168eb`）—— 列出 `docs/learning/` 全部 8 篇文档，并列出 Phase C/D 与 v0.11+/v0.14 的设计方向（均未实现）

### 状态

项目自 v0.10.3 起暂停更新，作为完整学习案例存档。Phase C（自主 Agent 评测）、Phase D（QLoRA 微调）、v0.14（剧本驱动重构）等方向已在 README 留作未来参考。

---

## [v0.10.1] - 2026-05-09

**v0.10 体验修复包 — 回合还原 / NPC 关系感知 / 场景一致性**

围绕 v0.10 多 Agent 实战发现的几个具体痛点：玩家"重试"无法真还原状态、NPC 反应脱离当前关系、不在场的 NPC 莫名出现。

### 新增

#### 🔄 回合还原（v0.10.5 F1）
- **`MessageRow.snapshot_json` 列**（V042 迁移）—— run_turn 开头序列化所有可变状态：CharState（hp/sanity/inventory）/ Session（doom/scene_turn/world_time/pc_mood/recall_pending/topology_warning）/ Screenplay（current_chapter/completed_events/chapters）/ NPCs（favor/emotion/affinity/state/last_seen_turn/current_location/last_initiative_turn/notes/revealed/faction_id）/ Locations / LocationEdges / HiddenEvents / Factions / PlotThreads / PCGoals
- **`delete_last_turn` 真还原** —— 反序列化快照后恢复所有可变字段；删除该回合**新建**的行（NPC / Location / LocationEdge / HiddenEvent / Faction / PlotThread / PCGoal）。"重试上一回合"现在能彻底撤销那回合的所有副作用，玩家不会带着错误的 stats / 错位的 favor 进下一次尝试。
- 老存档 message 行 snapshot_json 为空 → 跳过 restore（向后兼容降级到原 delete_last_turn 行为）。

#### 🗺️ NPC 常驻场所 + 首次出场铺垫（v0.10.5 F2）
- **outliner 新增 schema** —— `chapters[].main_locations`（本章主要场所）+ `main_characters[].primary_location`（每个主要 NPC 的常驻场所）
- **key_facts 注入** —— GM prompt 每回合看见"## 本章主要场所"+"## 主要 NPC 常驻场所"
- **铁律 36** —— NPC 首次相遇必须满足 (a) PC 当前在该 NPC 的 primary_location 或 (b) 近 2 回合 emit 过 `<plot_event type="encounter_setup">` 铺垫
- **Python 软校验** —— 新建 `service/encounter_check.py`：apply_tags 后扫本回合 say/npc_update，对违反铁律 36 的首次出场写"⚠️ NPC 凭空出场"警告到 `Session.topology_warning_json`，下回合 _build_key_facts drain 注入 GM prompt 强制补 encounter_setup。不拒绝主流避免 SSE 中断。

#### 🤝 NPC 关系感知 + favor_delta 输出（v0.10.6）
- **修复 v0.10 路径下 NPC.favor 永远不变的根因** —— Scene agent 被禁止 emit `<npc_update>`，NPC actor 之前 prompt 只列了 emotion delta 没列 favor_delta，导致两边都没人改 favor。前端 UI 一直显示 0。
- **npc_actor_template 新增"# 你和 PC 的关系"段** —— 注入当前 favor 数值 + 标签（≥30 友好 / ≥10 正面 / 中立 / ≤-10 冷淡 / ≤-30 敌对）+ affinity 多维（信任 / 羁绊 / 恋慕 / 敌意 等）+ 最近 2-3 次 PC↔本 NPC 实际对白对（regex 抽取）
- **铁律：反应首先取决于关系状态，archetype 只是底色** —— 关系冷淡时即使 archetype 是热情商人也会冷淡反应；关系信任时即使 archetype 是冷酷军人也会比对陌生人柔和
- **NPC actor 现在会 emit favor_delta** —— 救/帮/兑现承诺 +5..+15；信任/求助 +3..+8；撒谎被识破/失约 -5..-15；伤害/背叛 -15..-30；普通对话不 emit；后端 `_apply_npc_update` 自动 clamp ±100

#### 🎯 Scene-cued NPC fan-out（v0.10.7）
- **修复"不在场 NPC 也出来说话"的 bug** —— 之前 `_select_on_stage_npcs` 用 DB 状态（pinned + last_seen ≤ 3）选 fan-out 名单，与"Scene narrative 里此刻在场"脱节；pinned NPC 总会被强制 fan-out 即使他/她这回合根本不在 PC 周围
- **Scene 现在 emit `<npc_cue speaker intent>`** —— Scene agent 写完场景后明确点本回合在场且应反应的 NPC + GM 给的反应方向（"紧张地警告 PC 危险将至" / "对 PC 撒娇求带"）；不在场的 NPC 不要 cue
- **Orchestrator 仅 fan-out 被 cue 的 NPC** —— 每个 NPC actor 收到自己的 cue.intent 作为高优先级方向（prompt 靠前的"🎯 GM 给你的本回合方向"段）；按 cue 顺序透传给 isolated session 并行 / 顺序 fallback 两条路径
- **0 cue 时 fallback** 到旧 `_select_on_stage_npcs`（向后兼容老 prompt / 抽风模型）
- **结果**：DB 上 pinned 但 Scene 没 cue 的 NPC = 这回合完全沉默（不再"穿越"到当前场景）；Scene 写在 narrative 里的 NPC = 必须 cue → fan-out → NPC 自己接话

### 修复

- **设为默认模型 500（"网络错误"）** —— `ModelConfig.is_default` SQLAlchemy Mapped 字段从未定义；DB 列虽在迁移里加了，但 ORM 类没字段 → `update().values(is_default=False)` AttributeError 500
- **V036 迁移漏写到 db/base.py** —— 默认模型 release 时迁移逻辑没进文件，老 DB 启动 init_db 不应用 → "no such column: is_default"。补上 `_V036_MIGRATIONS` 后 init_db 自动加列
- **角色状态显示"尚未初始化"+ 背包"空"** —— `create_session` 调 `CharState(session_id=sid)` 直接建空 CharState，没拷 `Character.base_stats_json` → 玩家从 wizard 设的初始 hp/sanity 从 turn 0 就丢失。改为查 Character 行后用 base_stats_json 初始化 `CharState.stats_json`
- **AI 灵感推荐 cryptic 错误信息** —— `_stream_text` 拿到空响应直接抛 `JSONDecodeError("Expecting value: line 1 column 1")`。改成抛 `ValueError("LLM 返回空内容（可能：API 限额 / 模型不支持 JSON mode / 鉴权失效 / 推理模型把全部输出当成隐藏 reasoning）")` 让用户能看懂

### 数据库

- 新列：`messages.snapshot_json`（V042 迁移）；`model_configs.is_default`（V036 迁移补回）
- 新文件：`service/encounter_check.py`、`service/turn_snapshot.py`、`prompts/npc_actor_template.py`（已有，扩展 schema）

### 测试
- 后端测试 548 → 565（新增 17 个用例）
- 主要覆盖：snapshot/restore 三种回退场景、encounter_check 4 种判断、relationship 标签 + favor_delta 解析、npc_cue fan-out 控制 + 0-cue fallback

### 开发者注意

- v0.10.5 后 delete_last_turn 会真还原 turn 副作用（之前只删 messages + agent_messages）。如果你有自定义 state_apply 处理器写了未在 snapshot 范围内的字段，需要扩展 `take_snapshot` / `restore_snapshot`
- v0.10.7 后 Scene prompt 变化：必须 emit `<npc_cue>` 才能触发 NPC fan-out。模型纪律差时会 fallback 到老逻辑，但理想情况下 Scene 学会按 narrative 描述 cue 在场 NPC

---

## [v0.10.0] - 2026-05-09

**多 Agent Stateful 跑团引擎 — Director / Scene / per-NPC 各自独立对话历史**

主轴：把单 LLM GM 拆成 stateful 多 Agent，从根本上解决「张冠李戴」+「单 LLM 同时管长期剧情和短期场景导致节奏差」两大根本问题。Director 看长期、Scene 流式写场景、每个主要 NPC 自己一条对话流——三方协作通过 SSE 合成给玩家。配套新加 LocationEdge 防场景拓扑漂移。

### 新增

#### 🎬 多 Agent Stateful 架构（核心）
- **Director agent** —— 长期剧情决策；每 5 回合一次背景跑，重大事件（章节切换 / `<plot_turn impact="major">` / hp/sanity ≤5 / hidden_event 到期）同步触发。输出 `<plot_directive>` 块（主推目标 / NPC 重点 / 节奏 / 禁止事项），注入 Scene 和 NPC actor 的 prompt。
- **Scene agent** —— 短期场景执行；prompt 收窄为 narrative + pc_action + dice + state_change + 剧情标签，**禁止替 NPC 说话**。复用现有 `messages` 表做 stateful 历史。
- **Per-NPC stateful actor** —— 每个主要 NPC 一条独立 `agent_stream`；prompt 锁定 archetype / gender / purpose；只输出 `<say>` + `<npc_update>`；强制 speaker/name 与本 NPC 一致。
- **Orchestrator** —— 单回合协调器：Director 决策 → Scene 流式 → NPC fan-out 并行（每个 NPC 独立 SQLAlchemy session）→ aggregator 按时间线合并 yield。
- **智能排序**（决定 yield 顺序，不影响 LLM 调用）：PC 直接 cue 的 NPC > 高情绪 NPC > 其余按 last_seen_turn。
- **历史压缩** —— 每回合主提交后跑一次：Director threshold 30 / keep 10；NPC 25 / 8。旧消息被 summarizer LLM 压成单条 `is_summary` 行，保留长期记忆同时控制 token。
- **delete_last_turn 同步回滚** —— 玩家「重试」时，agent_streams 也同步 pop 当前 turn 的私有历史，避免 NPC 下回合「记得」实际上没发生的事。
- **`use_v10` 设置开关** —— 默认 `True`；老存档自然走 legacy 单 GM 路径直到首次 v10 触发建立 streams。GameView 设置面板暴露开关。

#### 🗺️ 场景拓扑系统
- **`LocationEdge` 表** —— 4 种 relation：`contains`（A 包含 B，如修道院 contains 实验室）/ `adjacent`（同层相通）/ `connects`（通过特定途径）/ `blocked`（已知存在但当前不可走）；`(session_id, from_loc_id, to_loc_id, relation)` 四元唯一约束保证 GM 重复 emit 幂等。
- **`<location_edge from to relation description>`** GM 标签 —— Scene prompt 加铁律：首次 emit `<location_enter>` 时必须紧跟 `<location_edge>` 锁住空间关系。
- **key_facts 周边拓扑块** —— 每回合刷新「## 周边拓扑（已确认，禁止违背）」段，对抗 summarizer 把空间关系糊掉的根因。
- **Python 强校验** —— `_apply_location_enter` 拦截不可达跳跃；不可达时把警告写入 `Session.topology_warning_json`，下回合 `_build_key_facts` drain 一次注入「⚠️ 上一回合拓扑越界」段强制 GM 补 edge。

#### 🎛️ 默认模型设置
- **`ModelConfig.is_default` 字段 + V036 迁移** —— 用户显式标记的默认模型；ModelsView 加「默认」列（★）+「设为默认」按钮，互斥写入。
- **`POST /model_configs/{id}/default`** 接口 —— 先全部清零再置 1。
- **`modelsStore.preferredId()` 帮手** —— Wizard / SessionsView 创建存档自动选默认模型替代「items[0].id」盲选第一条。

#### 🔍 Debug 视图增强
- **GET `/sessions/{id}/agents`** 新接口 —— 列每个 stream 的最近 12 条消息 + last_run_turn。
- **DebugView Agents tab** —— `AgentsDebugPanel.vue` 按 kind 分组（🎬 Director / 🎭 NPC: 名字），summary 行高亮；`pollIntervalMs=5000` 自动刷新让玩家发完一轮就能看到 director / NPC 流更新。

#### 🎯 Director snapshot 增强（v0.10.3）
- 不再只有 `turn / doom / scene_turn_count`：注入 PC vital state（hp / sanity / stamina / level）、当前章节 + 主线 done/total + 下一 pending event 描述、active hidden_events 倒计时、最近 8 回合 plot_turn major 决策日志。
- 同步触发标志位真值计算：`chapter_advanced_last_turn` / `major_plot_turn_last_turn` 从上回合 `events_json` 扫，`hp/sanity` 从 CharState 取，`hidden_event_due` 按 severity 算（severity 1:5/2:3/3:2 turns 阈值）—— Director 能在重大事件时立即被 sync 触发，不再只靠 5 回合 interval。

### 修复

- **NPC 卡 favor / emotion 不刷新** —— GameView 每回合 onDone 后只刷新 `current_location`，没拉 favor / emotion / state；改成全量 refresh。
- **NPC reveal 阈值在 GM dossier 失效** —— `_npc_to_dict` 已经叠加阈值规则（last_seen_turn>0 → reveal description/state/favor 等），但 `_format_npc_dossier`（GM prompt 用）只读 `revealed_json` 没叠加，导致玩家明明已经互动 GM 还在说「未揭示」。抽出 `_effective_reveals` 共享 helper。
- **tier-1 删存档时剧本被一起带走** —— wizard / `_auto_generate_screenplay` 给 Screenplay 加 `world_id`；`delete_session_cascade` 把世界级剧本 detach + 重置进度（`current_chapter=1` / `completed_events_json="[]"`）而不是 delete，玩家可以再开新存档复用同剧本。
- **NPC 主动发起逻辑误杀「反应慢一拍」** —— `find_initiative_npc` 现在用 `last_spoke_turn`（扫 `events_json` 里 `<say>` 事件）替代 `last_seen_turn`（v0.10 narrative 提到 NPC 名就 bump），让「在场没说话的 NPC 下回合能补一句」成立。`_INACTIVE_TURNS_MIN` 从 2 降到 1。
- **删存档 / NPC / 世界时 ChromaDB 资源泄漏** —— `npc_memory.delete_npc_memory(npc_id)` + `world_rag.delete_world_index(world_id)` 在 cascade 时调用，避免 `~/.dzmm/chroma_npc/` 和 `~/.dzmm/chroma/{world_id}/` 越长越大。

### 数据库
- 新表：`agent_streams`（5 列）、`agent_messages`（8 列）、`location_edges`（6 列）
- 新列：`model_configs.is_default`、`sessions.topology_warning_json`
- `_V036` / `_V040` / `_V041` 迁移 additive，可从 v0.9 直升

### 测试
- 后端测试 491 → 548（新增 ~57 个用例）
- 主要覆盖：agent_streams CRUD/历史/压缩/回滚、Director + 7 类触发条件、Scene、NPC actor + sort + scene_context、orchestrator e2e、location_edges 拓扑校验、NPC reveal 阈值、location 删存档保留剧本、ChromaDB 删除清理、默认模型互斥、debug agents 接口、initiative `last_spoke_turn`

### 铁律修正
- 双 27（派系一致性 + 场景效率）拆为 27 / 28；后续编号 28 → 29、29 → 30、30 → 31、31 → 32、32 → 33、33 → 34、34 → 35。

### 开发者注意
- v0.10 默认 `use_v10=True`；想用老 v0.9 单 GM 路径需 `PATCH /sessions/{id}/settings { "use_v10": false }`，或前端 GameView 设置面板关闭。
- NPC fan-out 用每 NPC 独立 SQLAlchemy session；`run_turn` 透传 `session_maker`；`session_maker is None` 时 fallback 走顺序模式（保留向后兼容）。
- 已知限制：peer_lines 在 v0.10.2 中移除（同回合 NPC 不再看到彼此当回合的话），二阶动态靠 npc_actor 自己的 history（前几回合关系记忆）即可。

---

## [v0.9.0] - 2026-05-07

**深度 Pack — Dice 演出 / NPC 长期记忆 / 派系系统 / 战斗聚合 / 大事记**

主轴：让每次 dice 检定从「一行字」升格成「叙事密度峰值」——感官细节 + NPC 反应 + 翻滚动画。配套铁律改 GM 节奏：非 dice 回合白描快推进，dice 回合慢镜头。同时给 NPC 长期记忆 + 派系厚度，让世界从面变成体。

### 新增

#### 🎲 Dice 演出系统
- **`<dice>` 三段式 schema** —— 机制层（category + outcome + d20 + DC）+ `<scene>` 子标签（2-4 句感官细节）+ `<reaction speaker mood>` 子标签（NPC 反应）
- **7 类 dice category** —— combat / stealth / persuasion / arcane / athletics / perception / knowledge / generic
- **4 级结果** —— crit_success（金色 + 闪光）/ success / fail / crit_fail（红色 + 阴影）
- **DiceShowcase 组件** —— 三段式卡片，stage-sequenced 动画揭示（翻滚 0-800ms → 结果 800ms → scene 1100ms → reactions 1500ms 起逐条）
- **D20Roll SVG 组件** —— 六边形 d20 + animate-spin 翻滚 + 数字弹出
- **铁律 31** —— dice 必须详写：scene 不可少，相关 NPC 在场必须 reaction
- **铁律 32** —— 节奏倾斜：非 dice 回合白描，dice 回合慢镜头；不要每段都堆细节
- **新示范5** —— gm_few_shot 加 stealth 成功正面示例 + bare-dice 反面示例

#### ⚔️ Combat 聚合视图
- **`<combat_start>` / `<combat_end winner="..."/>`** 标签 —— enemies 列表（JSON 数组）作为内容
- **CombatPanel 组件** —— 跨回合包裹 combat_start..combat_end 之间的所有 turn 卡片，header 显示「⚔️ 战斗中」+ HP 条（PC + 每个敌人）
- **TurnArticle 抽出** —— 把 MessageList 里的单回合渲染独立成可复用组件，便于 CombatPanel 包裹

#### 🧠 NPC 长期记忆（ChromaDB）
- 每个 NPC 一个 `npc_mem_{npc_id}` collection（存储路径 `~/.dzmm/chroma_npc/`）
- 每次 `<say>` 后 `asyncio.create_task` 异步把内容嵌入对应 NPC 的 collection（速度不阻塞 SSE）
- `_build_key_facts` 时对在场 NPC（最多 4 个）retrieve top-3 与当前行动相关的回忆，注入「## XXX 私人记忆（仅 GM 可见）」段
- 完全 fail-soft：Ollama / ChromaDB 任意环节出错都静默降级（记忆是软增强，不能阻塞主流程）

#### ⚖️ 派系 / 势力系统
- **`factions` 表** —— name / ideology / description / leader_npc_id / pc_reputation (-100..100) / hostile_to / allied_to
- **NPC.faction_id** 列 —— 每个 NPC 可关联到一个派系
- **`<faction_create name ideology hostile_to allied_to>...</faction_create>`** —— 创建派系（idempotent by name）
- **`<faction_change name="X" rep_delta="N"/>`** —— PC 名声变化（自动 clamp ±100）
- **GET /sessions/{id}/factions** —— 列出该会话的所有派系
- **FactionGraph 组件** —— StatePanel ⚖️ 势力 抽屉，按口碑配色（盟友绿 / 敌人红 / 中立灰），显示 hostile_to/allied_to 关系
- **GM prompt 注入「## 势力关系」段** —— PC 在各派系中的口碑 + 立场
- **铁律 27** —— NPC 行为应与所属派系利益一致

#### 📅 历史时间线抽屉
- **Timeline 组件** —— StatePanel 📅 大事记 抽屉，按 turn 时间轴展示 plot_event（new_quest / hook_introduced / major_event / location_entered / hook_resolved），按 type 配色 + 图标
- 复用现有 `threads` prop，不新增 API 调用

### 数据库
- 新表：`factions`（10 列）
- 新列：`npcs.faction_id`（nullable FK to factions）
- `_V033_MIGRATIONS` additive，可从 v0.8 直升

### 测试
- `tests/test_stream_parser.py` +3（dice nested / legacy / combat+faction tags）
- `tests/test_npc_memory.py` 8 项（graceful degradation）
- `tests/test_factions.py` 5 项（list / create+change / idempotent / clamp / JSON 解析）
- 总后端测试 430 → 446

---

## [v0.8.0] - 2026-05-07

**沉浸感 Pack — 资源系统 / Wizard 集成 / 自动播放 / 时间日历 / 快捷动作 / NSFW 开关**

围绕一个底座（资源系统）+ 五个产品级功能展开：玩家在 Wizard 阶段一次性把美术、音乐、场景资源都设好；进入游戏后按 location/chapter 自动切换；GM 可推进世界时间；输入框给 8 个快捷动作；会话独立 NSFW 自由度。

### 新增

#### 🎨 资源系统底座
- **`Asset` 表 + `AssetLink` 多对多** —— 任意 owner（world / character / npc / screenplay / chapter / location / session）可挂载图像 / 音频，按 `slot` 区分用途（cover / avatar / bgm / ambient / scene）；支持 `local`/`builtin`/`http` 三种来源
- **`/assets` API** —— list / upload / serve / delete / attach / by_owner 6 个端点
- **builtin 素材包脚手架** —— `packaging/assets/builtin/` 目录树 + `manifest.json` 自动播种机制；v0.8.0 不打包二进制资源（CC0 curated pack 留作 follow-up），系统对仅用户上传的场景已完全可用
- **`<AssetPicker>` Vue 组件** —— 通用：上传 / 库选 / 清除；`archetypeFilter` 让匹配的 builtin 头像排序靠前

#### ✨ Wizard 资源集成
- **Step 2** 世界封面图（attach 到 world）
- **Step 4** 每个 NPC 的头像（archetype-aware 排序，attach 到 npc）
- **Step 5** 每章节默认 BGM（attach 到 session，slot=`chapter_bgm`，extra=`{chapter}`）
- **Step 6 review** 新增「场景资源」区域：用户可手动添加场所，每个挂场景图 + 环境音
- `finalize_wizard` 返回 `{session_id, world_id, npc_ids}` 让前端拿到 ID 做 attach

#### 🎬 游戏中自动播放
- **`SceneBackdrop.vue`** —— 当前场景图作为半透明背景，0.7s fade transition
- **`useAmbientAudio` composable** —— BGM + ambient 双轨独立 crossfade（2s requestAnimationFrame）
- **`<location_enter>` 触发** —— 加载该 location 的 scene + ambient
- **`<chapter_advance/>` 触发** —— 切换该章节的 BGM
- **`<bgm mood="..."/>` 标签** —— GM 可显式切换 BGM 情绪（tense / calm / battle / exploration / sad / triumphant）

#### 🕐 时间 / 日历系统
- **`Session.world_time_json`** = `{day, period, weather}`，默认 `{1, "morning", "clear"}`
- **`<time_advance hours / period / weather / day />`** 标签 —— 推进世界时间（4h/period 步进，跨 midnight 自动 day+1）
- **GM prompt** 注入 `## 当前时间` 段；新增铁律：长途旅行 / 休息 / 过夜 / 跨场景必须 `<time_advance>`
- **StatePanel 顶部显示** —— 「🕐 第 N 天 · 黄昏 · 阴」

#### ⚡ 快捷动作模板
- 输入框 chips 从 4 项扩到 8 项：⚔️ 行动 / 🔍 调查 / 💬 交谈 / 🥷 隐匿 / ⚔️ 攻击 / ⏳ 等待 / 🎒 物品 / 🎲 技能
- 点击后预填到输入框 + 光标定位

#### 🔞 内容自由度（NSFW）
- **会话设置** `content_level: safe | mature | unrestricted`
- **GM prompt** 按级别注入「## 内容尺度」指令（safe 默认；mature 允许暴力 / 亲密 / 黑暗主题；unrestricted 完全开放）
- SessionsView 创建对话 + GameView 设置对话都有下拉选择

### 数据库
- 新表：`assets`（13 列含 kind / source / file_path / mime / dimensions / tag_json）+ `asset_links`（owner_type/id/slot/extra_json）
- 新列：`sessions.world_time_json`
- `_V032_MIGRATIONS` additive，可从 v0.7 直升

### 测试
- `tests/test_assets.py` 5 项（list / upload / mime guard / attach / delete cascade）
- `tests/test_world_time.py` 13 项（formatter + handler 各 case）
- 总后端测试 412 → 430

---

## [v0.7.0] - 2026-05-07

**TTS 全面重构 · Debug 工具链 · Wizard AI 助手 · LLM 兼容性加固**

自 v0.6.0 以来积累的 70 余个 commit 一次性发版，覆盖四条主线：本地 TTS 引擎全面接入 + 局域网直连、Konami 触发的 Debug 工具链（LLM 原始数据查看 + 数值编辑器）、Wizard 创角全程 AI 推荐、本地 LLM（LM Studio / Ollama）兼容性 / 解析鲁棒性。

### 新增

#### 🔊 TTS 系统重构（多引擎 + 局域网）
- **内置 4 种 TTS 模式** —— `edge-tts`（云端微软声音）/ `kokoro-onnx`（本地 ONNX）/ `cosyvoice`（本地 sidecar，uv 隔离环境）/ 局域网直连 OpenAI 兼容服务（`direct URL`）
- **`packaging/tts/`** —— Kokoro / CosyVoice 一键安装 / 启动 / 卸载脚本，跨平台（macOS / Windows / Linux）
- **TTS Settings 卡片三层 UI** —— 模式切换 / 音色下拉 / 安装 - 启动 - 卸载状态机；含中文 TTS 推荐（CosyVoice / ChatTTS / EmotiVoice / Qwen3-TTS）
- **NPC / PC 自动音色** —— `voice_map.ts` 把 `archetype` 映射到合适的 edge/kokoro 音色，NPC 创建对话框自动填默认值；CharacterCardDrawer 显示 PC 音色 + 试听按钮
- **每说话人过滤**（旁白 / PC / NPC 三个独立开关）—— 游戏页 🔊 弹层切换，配置写 localStorage
- **`GET /tts/probe`** —— 检测外部 TTS 服务是否可达（依次试 `/health`、`/v1/models`、`/`），方便 LAN 模式排查

#### 🐛 Debug 工具链（Konami 触发）
- **Konami 码激活**（`stores/debug.ts`）—— `↑↑↓↓←→←→BA` 切换 debug 模式，状态写 localStorage
- **每回合 LLM 原始数据查看** —— GM 卡片右上 🐛 按钮 → 弹窗显示完整 prompt（按 role 分色）+ 原始 response + token 计数；通过 `messages.prompt_json` 列持久化
- **数值编辑器**（`DebugPanel.vue`）—— 厄运值滑条（0-100）/ turn_count / scene_turn_count / PC 属性逐项编辑，独立保存按钮
- **后端 API** —— `GET / PATCH /sessions/{id}/debug_state`、`debug_mode` 加入 `PatchSettingsRequest`、`/messages/{id}/debug` 返回完整 prompt+response

#### ✨ Wizard 创角 AI 助手
- **AI 灵感推荐** —— 自动生成 4 套「题材 + 主题 + 主角原型」组合，可「换一批」（`generate_suggestions`）
- **Step 4 NPC AI 面板** —— 点击 AI 推荐 NPC 直接加入列表，无需复制粘贴
- **archetype suggestions + theme refine** —— 题材 / 主题 / 原型独立 LLM 生成
- **流式 wizard** —— 世界书 / 角色 / NPC / 剧本生成全部走 SSE，进度可视
- **角色启动物品强制含货币** —— 适配世界观：奇幻金币 / 现代港元 / 科幻积分卡等

#### 🤖 LLM 兼容性 / 解析鲁棒性
- **LM Studio `response_format` fallback** —— 不支持 `{"type":"json_object"}` 的本地服务器返回 400 时自动重试无 json_mode，per-instance 缓存判定结果
- **JSON 解析器加固** —— `_extract_json` 同时支持 `{...}` 和 `[...]` 根；折叠模型回写的 `{{ }}` 双重大括号；strip trailing commas；Python 字面量（`True`/`False`/`None`）→ JSON
- **`_unwrap_npc_list`** —— 兼容裸数组、`{"npcs": [...]}`、`{"NPCs": [...]}`、`{"characters": [...]}` 等多种返回形态
- **outliner template 修复** —— `_OUTLINER_SYSTEM` 是普通字符串而非 f-string，移除 `{{`/`}}` 转义，否则模型会照抄回 `{{"chapters":...}}`
- **NPC per-NPC 并发** —— `run_npc_post_pass` 改为 `asyncio.gather` 逐 NPC 并行，独立 prompt 含完整 character profile（Phase B 增强）
- **Ollama 模型可用性检查** —— `GET /model_configs/{id}/check`、Wizard 横幅提示模型未拉取、SessionView 显示「修复」对话框

### 改进

- **NPC 在场显示** —— StatePanel 新增「此处人物」段，按 `current_location` 过滤当前场所 NPC，附 favor 颜色点 + 状态文本
- **`updateSettings` 整合** —— 移除重复的 `patchSettings`，单一 API 方法支持 `narrative_polish` / `director_pass` / `debug_mode`
- **TTS UI 简化** —— 删除 WebSpeech / 旧 Kokoro 模式，两层 UI（mode + voice）
- **CosyVoice 修复** —— `is_installed` 文件名修正（cosyvoice.yaml 而非 cosyvoice2.yaml）、503 提示加可执行操作、cwd 修复、依赖跳过 `openai-whisper`
- **Tauri Spec 修复** —— `bundle espeakng_loader / kokoro_onnx / phonemizer / language_tags` 数据文件、langchain/langgraph hidden imports
- **Pinia 配合 Element Plus** —— 三个 TTS 开关从 `v-model="store.x"` 改为 `:model-value` + `@change` 显式 setter（避免绕过 store 边界）

### 修复

- **PC 对话开头多余 `#`** —— `useGameTurn.ts` 在 `pc_action` 事件处剥离 `#name：` 前缀
- **rawContent 顺序错乱** —— GM narrative + say 现在按文档顺序交错（之前总是 narrative 先于所有 dialogue）
- **XML 格式漂移** —— 老对局 summary 后 GM 改回纯文本，`_check_xml_drift` 检测连续 ≥2 条无 XML 的 assistant 消息时自动注入格式提醒
- **Debug 历史回放** —— `Turn` 重建时从 `MessageRow.id` 填 `msgId`，🐛 按钮在重新加载的会话上也可用
- **Cargo.lock 滞后** —— app version `0.1.0` → `0.7.0` 同步

### 依赖新增

- 后端：`edge-tts>=6.1`、`kokoro-onnx`（本地 ONNX 引擎）；CosyVoice 通过 sidecar 隔离不入主依赖
- 打包：`numpy`、`onnxruntime`、`soundfile`、`espeakng_loader` 加入 PyInstaller hidden imports

---

## [v0.6.0] - 2026-05-03

**Phase C — 自主 Agent 自动评测**

玩家 Agent 自动生成行动 + 评审 Agent（LLM-as-Judge）每 10 回合打分，输出对比报告。支持单体 GM vs 多 Agent GM 质量对比。

### 新增
- **`eval/player_agent.py`** — 玩家 Agent：读取对话历史 → LLM 决策 → 输出下一步行动
- **`eval/judge_agent.py`** — 评审 Agent：LLM-as-Judge 对 4 个维度打分（剧情推进/规则违反/RP沉浸感/骰子准确性）；三级 JSON 解析 + fallback 默认分
- **`eval/runner.py`** — 评测编排器：`EvalConfig` + `run_eval()`，N 回合自动对局，评分写入 `feedbacks` 表
- **`eval/report.py`** — Markdown 对比报告生成器，均值表格 + 逐检查点详细分
- **`eval/cli.py`** — CLI 入口：`python -m dzmm.eval.cli --session-id 1 --turns 20 [--compare --session-id-b 2]`
- **报告输出** — 自动保存到 `~/.dzmm/eval/report_{timestamp}.md`

### 使用
```bash
# 单局评测
python -m dzmm.eval.cli --session-id 1 --turns 20

# 对比评测（单体 GM vs 多 Agent GM）
python -m dzmm.eval.cli --session-id 1 --session-id-b 2 --turns 20 --compare
```

---

## 版本号约定

`MAJOR.MINOR.PATCH`：
- **MAJOR**：测试 / 正式 / 季度级大版本（0 = 测试阶段；1 = 正式发布之后）
- **MINOR**：核心功能变更（如「剧本驱动」「编年史系统」整套机制）
- **PATCH**：小修复 / 小增强（bug fix、UI 微调、文档）

历史版本（v0.1 - v0.13）属于测试期 PATCH 增量；自 0.0.14 起改用三位数显式标记。

## [v0.5.0] - 2026-05-03

**Phase B — LangGraph 多 Agent GM**

GM 管线拆分为三阶段：LangGraph 规则预处理 Agent（StateGraph + 条件边）→ 主叙事流式生成（不变）→ NPC 后处理 Agent。通过 `use_graph` 会话设置开启。

### 新增
- **`service/gm_graph.py`** — LangGraph `StateGraph` 预处理图：`rules_node`（规则分析）→ 条件边（有检定 → `dice_enrich_node`，无检定 → END）→ 返回增强版 `key_facts`
- **`run_npc_post_pass()`** — 主叙事完成后运行，检查在场 NPC 是否有遗漏反应，产出额外 `<npc_update>` 事件
- **`prompts/rules_template.py`** — 规则预处理 Prompt（行动类型 + 技能检定 + 叙事指令，三行格式）
- **`prompts/npc_react_template.py`** — NPC 后处理 Prompt（补充在场 NPC 未显示的反应）
- **`use_graph` 会话设置** — 在 `session.settings_json` 中设 `"use_graph": true` 即可启用；默认 false，不影响现有行为
- **向后兼容** — `director_pass` 设置保留，`use_graph` 和 `director_pass` 可独立选择

### 依赖新增
- `langgraph>=0.2` — StateGraph, 条件边, ainvoke

## [v0.4.0] - 2026-05-03

**Phase A — LangChain RAG 世界书检索**

世界书 Markdown 分块向量化存入 ChromaDB；每回合检索 top-4 最相关片段注入 Prompt，减少本地 7B 模型的上下文压力，支持大型世界观。

### 新增
- **`service/world_rag.py`** — OllamaEmbedder（实现 LangChain Embeddings ABC）、`index_world()`（分块+向量化）、`retrieve_world_context()`（top-k 检索）、`get_world_md()`（优雅降级决策函数）
- **`POST /worlds/{id}/reindex`** — 手动触发世界书重新索引（202 Accepted，后台异步）
- **自动重索引** — 世界书 create/update 时 fire-and-forget 触发 `index_world_async()`
- **`run_turn()` 集成** — 新增 `ollama_base_url` 参数；世界已索引时用 RAG 替代全文注入
- **短世界书 fallback** — 世界书 < 800 字符或未索引时，静默回退到全文注入

### 依赖新增
- `langchain-text-splitters>=0.3` — RecursiveCharacterTextSplitter
- `langchain-core>=0.3` — Embeddings ABC
- `chromadb>=0.5` — 本地向量数据库（存储在 `~/.dzmm/chroma/{world_id}/`）

## [v0.2.2] - 2026-05-01

**P1 GM/Prompt 改进**

针对实玩 72 回合发现的剧情卡顿、NPC 被动、dice 重复值等 GM 行为问题，加 4 条铁律 + dice 监控 + wizard NPC reveal 调整。

### 新增
- **铁律 24 加严**（剧情强制推进）：1-3 回合 → **1-2 回合**；4 回合不 emit `event_complete` = 划水；GM 应主动用 NPC/环境/hidden_event/plot_event 推 PC 回主线
- **`_build_key_facts` 注入「⚠️ 剧情强推」段**：检测当前章节 5+ 回合无 main_event 完成 → 注入下一个 pending event 名 + 强制 emit 指令；老 completed_events_json 无 turn 字段时按 turn=0 fallback（72 回合卡顿场景立即触发）
- **`_apply_event_complete` 记录完成 turn**（之前只记 chapter/event_idx/type）
- **铁律 25 单轮内信息顺序**：narrative / pc_action / say 严格按故事时间线；`say` 紧跟引发它的 pc_action / narrative；few_shot 加示范 3 演示
- **铁律 26 NPC 每 2-3 回合主动行动**：除响应 PC 外，至少一个 NPC（pinned 或 emotion ≥ 50）主动搭话 / 与其它 NPC 互动 / 推自己的 plot_thread；禁「PC 不动 NPC 也不动」死场景
- **铁律 27 dice 失败必产生负面后果**：5 类范例（关系恶化 / 物品损耗 / 线索错失 / 敌意 NPC 出现 / 时间失控）；大失败 d20=1 必须 2-3 项叠加；成功 ≥ DC+5 emit `character_xp +20`
- **dice 监控**（`service/state_apply/dice_monitor.py`）：检测最近 5 条 message 连续 3 次相同 d20 → key_facts 末尾注入「⚠️ Dice 警告（仅 GM 看）」段提示 GM 必须不同（治实玩 d20 总是 9）
- **wizard NPC reveal 默认改**：`finalize_wizard` pinned NPC 创建时只 reveal `name`（之前默认 reveal name + description + purpose + archetype），让 GM 在游戏中通过 npc_update reveal 字段逐步揭示

### 测试
- 后端 301 → 328（+27）

### 待办（v0.2.3 P2 UX）
- 自动开局 / 编年史完全删 / 默认行动改剧本导向 / 场所记录 / 同世界续作 + 选择性 NPC 复制 / 剧情线点击查看总结

---

## [v0.2.1] - 2026-05-01

**实玩 72 回合 P0 紧急修复**

实玩存档观察：24 NPC 表中 20 个是 NER 误抓垃圾、71+ 回合 GM 输出抄 prompt few_shot 段、events dialog 显示上一轮数据等 5 个 P0 bug。

### 修复
- **P0.1 NER 终极加严** —— v0.1.9 频率 ≥3 仍不够。本次：
  - 最少 3 字（不再允许 2 字，全删 2-char 路径）
  - skip PC 名子串（「塞巴/塞巴斯/奥斯特」是 PC 名片段，不再被抓）
  - 扩停用词表 70+ 词（「了你/我从/她轻/个叫/的一/的那/一丝/印着/标签」等实玩具体垃圾）
  - 首字门槛：「了/的/着/我/她/他/一/这/那/有/被/把/给/为/之/从」开头要求 ≥4 字
  - 加 3 个回归测试覆盖实玩 14 个具体垃圾词
- **P0.2 长上下文崩溃** —— GM 在 71+ 回合抄 prompt 里 few_shot 段是典型长上下文模型崩溃信号
  - 摘要器触发 20 → 10 回合（每 10 回合压一次）
  - recent_messages window 自适应：默认 12 / 30+回合 8 / 60+回合 6（防 prompt 无限膨胀）
  - few_shot 改写：`# 输出范例 / # 关键信息推进示范 / # 错误示范` 标题 → `--- xxx ---` 分隔符（避免 GM 抄成自己输出格式）；缩减 24.5%
  - activity_log 加 `turn_prompt_size` / `turn_prompt_warning` 事件（>12k token 警告）
- **P0.3 events dialog stale** —— openEvents 改 JSON deep copy + onClose nextTick 清空，修「日志艾琳娜显示院长」类不一致
- **P0.4 inventory 不显示** —— GameView onMounted 第一时间 hydrate state（含 inventory），不依赖延迟初始化
- **P0.5 parser unclosed warning 降级** —— `/unclosed/` 类错误 console.debug 不弹 toast（v0.1.9 后端 parser.finish() 已兜底）

### 测试
- 后端 290 → 301（+11：3 NER 实玩回归 + 8 长上下文 / window / token 估算）
- 前端 build 通过

### 待办（v0.2.2 + v0.2.3）
- P1 GM/Prompt 改进：剧情强推 / NPC 主动 / dice 失败反转 / dice 监控 / 信息顺序
- P2 UX：自动开局 / 编年史删除 / 默认行动改剧本导向 / 场所记录 / 同世界续作（含 NPC 选择性复制）/ 剧情线点击查看总结

---

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
