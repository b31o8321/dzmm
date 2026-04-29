# 更新日志

按 [Keep a Changelog](https://keepachangelog.com/) 风格，版本对应 git tag。

## [v0.8] - 2026-04-29（进行中）

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
