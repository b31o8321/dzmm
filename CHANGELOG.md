# 更新日志

按 [Keep a Changelog](https://keepachangelog.com/) 风格，版本对应 git tag。

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
