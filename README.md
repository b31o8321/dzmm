# dzmm

An AI-driven TRPG (tabletop role-playing) text adventure that runs on your own machine. The GM is a local or cloud LLM; you bring the world, character, and imagination. No subscription, no other players needed, no censorship beyond what your model has.

> **Status:** Active development. v0.6 is the latest release. See [CHANGELOG](CHANGELOG.md) for what each version brought.

## Quick start

### Option A: prebuilt (recommended)

1. Install [Ollama](https://ollama.com/download), then pull a model:
   ```bash
   ollama pull qwen2.5:7b
   ```
2. Download the latest release for your platform from [Releases](https://github.com/b31o8321/dzmm/releases):
   - **macOS (Apple Silicon)**: `dzmm_x.y.z_aarch64.dmg`
   - **Windows x64**: `dzmm_x.y.z_x64-setup.exe`
3. Open the installer:
   - macOS: drag to Applications. First launch: right-click → Open (Gatekeeper unsigned-app warning, click "Open" once).
   - Windows: SmartScreen will warn — click "More info" → "Run anyway".
4. Launch dzmm. The welcome dialog asks whether to enable phone access on your LAN (default: local only, safest).
5. Click 「跑团」→「+ 新开一局」. There are 4 preset worlds + characters. Pick one and play.

### Option B: dev from source

Prereqs: Python 3.11+, Node 18+, Rust stable, Ollama.

```bash
# Clone
git clone git@github.com:b31o8321/dzmm.git
cd dzmm

# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Frontend
cd ../frontend
npm install

# Start (3 terminals)
# 1) ollama serve
# 2) cd backend && .venv/bin/python scripts/run_dev.py
# 3) cd frontend && npm run dev
```

Open http://localhost:5173. For phone access, see [LAN access](#lan-phone-access) below.

## What you get

- **4 preset worlds** (cyberpunk Hong Kong / Taisho Japan horror / contemporary urban supernatural / xianxia 修仙) with matching characters, but you can create your own
- **Streaming narrative** — text appears word-by-word like a real GM is typing
- **Structured state tracking** — HP/sanity/inventory/NPC favor automatically tracked from `<state_change>` and `<npc_update>` tags emitted by the GM
- **Dice rolls** in standard rules mode (d20 + DC system, history shown in side panel)
- **Plot threads** — when the GM introduces a quest or hook, it's tracked across turns and re-injected into future prompts so the campaign stays coherent
- **Rolling summary** — once a session passes 10 turns, the past gets summarized to keep context manageable
- **Edit / regenerate last turn** — bad roll? Click 重新生成 or 编辑上一动作 and try again
- **Phone access** — opt-in LAN mode lets you play on your phone over WiFi (great for long sessions away from desk)
- **Conversation history persists** — close the app, come back later, your campaign is exactly where you left it

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Tauri shell (Rust)                                 │
│   • Spawns backend as child process on launch       │
│   • Hosts webview pointing at bundled frontend      │
│   • Kills backend on window close                   │
└──────────────────┬──────────────────────────────────┘
                   │
       ┌───────────▼────────────┐    ┌─────────────────┐
       │ FastAPI backend (8765) │───▶│ Ollama (11434)  │
       │  • /sessions/{id}/turn │    │ (you install)   │
       │    SSE streaming       │    └─────────────────┘
       │  • SQLite persistence  │
       │  • keyring for keys    │
       └───────────┬────────────┘
                   ▲
                   │ axios + fetch (SSE)
       ┌───────────┴────────────┐
       │ Vue 3 + Vite frontend  │
       │  • streaming parser    │
       │  • markdown render     │
       │  • Element Plus UI     │
       └────────────────────────┘
```

- Backend: Python 3.11+ FastAPI + SQLAlchemy 2.0 (async) + aiosqlite + httpx
- Frontend: Vue 3 + TypeScript + Element Plus + TailwindCSS + pinia
- Desktop: Tauri 2 (Rust shell, ~5MB) + PyInstaller-bundled backend (`--onedir`, ~45MB)
- Storage: SQLite at `~/.dzmm/dzmm.db`; logs at `~/.dzmm/dzmm.log` (5MB × 3 rotation); API keys in OS keychain

## Recommended models

GM prompt requires structured tag output. Reasoning-tuned models (`deepseek-r1`, `o1`-style) burn tokens in `<think>` blocks and skip our format — avoid them.

| Model | Size | Notes |
|---|---|---|
| `qwen2.5:7b` | 4.7 GB | **Best balance** for local; tag compliance is solid |
| `qwen2.5:14b` | 9 GB | Better narrative; needs ≥16GB RAM |
| `llama3.1:8b` | 4.7 GB | Solid alternative |
| `gpt-4o-mini` (cloud) | — | Excellent compliance, ~$0.08/h of play |
| `claude-haiku` (cloud) | — | Excellent compliance, similar cost |

Cloud models use the `openai_compat` config type — works with OpenAI, Doubao, Tongyi, DeepSeek, 零一万物, anything OpenAI-shaped.

## LAN / phone access

When the welcome dialog appears, choose 「启用手机访问」. The app will:
- Bind backend to `0.0.0.0:8765` (vs `127.0.0.1:8765`)
- Serve the bundled frontend over HTTP from the same port
- Show your Mac/PC's LAN URL as a banner — type that URL into your phone's browser

Caveats:
- Both devices must be on the same WiFi
- Some routers do AP isolation; if it doesn't work, check router settings
- Don't enable on untrusted networks (cafes etc.) — the backend has no auth

## Build from source

集中入口在 [`packaging/`](packaging/README.md)，最终产物落到 `packaging/dist/`。

```bash
# macOS / Linux
python packaging/build.py

# Windows（PowerShell from repo root）
.\packaging\build.ps1
```

需要单独跑某一段（只重打 backend、或沿用现有 backend-runtime 跑 tauri）见 [packaging/README.md](packaging/README.md)。

### CI

Pushing a `v*` tag (e.g. `v0.7`) triggers `.github/workflows/release.yml` which builds both platforms in parallel and publishes a GitHub Release.

## 路线图

完整规划见 [docs/superpowers/plans/](docs/superpowers/plans/) ，最近几个版本：

- **v0.7（已发布）** —— 游戏性：任务日志页、**NPC 攻略详情**（多维好感 / 动机 / 人设原型 / 钉住 / GM 召回 / 互动时间线 / 浏览所有 NPC）、角色 XP+升级、BGM+音效、角色立绘。性能：递归摘要压缩、模型预热。
- **v0.8（已发布）** —— **编年史 + 目标 + 易用性**：编年史页（Timeline UI + Era 分章）、PC 目标列表、首次启动引导、Tauri 自动更新。
- **v0.9（已发布）** —— **情绪系统 + GM 反应性**：NPC 5 轴情绪雷达（怒/爱/惧/敬/嫉）、PC 心情、NPC↔NPC 关系图、GM prompt 反应性原则、Playwright 端到端冒烟、release artifact 完整性检查。
- **v0.10（已发布）** —— **实玩反馈统一优化**：4 新标签（say / pc_action / hidden_event / scene_shift）、闭合标签错拼容错、隐性事件带引信、PC 身份铁钉、NPC 自动登记 NER 兜底、speaker 分气泡、事件详情 dialog、存档导出 JSON/MD、Enter 发送、prompt 铁律扩到 19 条 + 描写丰度 + 双视角解读。
- **v0.11（已发布）** —— **角色卡 + 钩子 + 数值锚定**：PC 角色卡抽屉、NPC 渐进信息揭示（reveal 字段 + ****）、PC 钩子驱动场景（能力/物品/弱点节奏化使用）、dice DC 表锚定属性、物品 narrative 显式引用、铁律扩到 21 条。
- **v0.12（已发布）** —— **姓名漂移根治 + 推进义务 + 帮助页**：UI 显示版本号、PC 姓名 repair 后端兜底（含 NPC 对白 mask）、数值 hover tooltip、`/help` 说明页、plot_event 去重（治重复登记）、铁律 22/23（关键信息推进 + 世界状态前进）。
- **v0.13（已发布）** —— **SSE 流式回归修复 + 铁律加狠**：修 v0.10 引入的 SSE 渲染 bug（displayParts）、plot 去重 normalize+0.6+多 type、铁律 22/23 改写为字面要求 + 禁止句式黑名单、few_shot 加正/反示范、后端版本对比警告。
- **v0.0.14（已发布，启用三位数版本号）** —— **玩家反馈收集**：GameView 加 💬 反馈按钮，反馈绑定 session（turn / message_id / 时间戳），含入存档导出 JSON/MD，方便开发者结合上下文优化。
- **v0.1.0（已发布，首个 MINOR 版）** —— **剧本驱动跑团**：开档调 LLM 生成结构化大纲（章节/主要 NPC/关键事件/完结）、5 套 genre 模板 + 自定义、GM 按主线推进 + 支线 PC 触发、4 新 GM 标签 + 铁律 24、剧本进度页 + 完结续写。
- **v0.1.1（已发布）** —— **调试模式 + e2e 修复**：Konami 序列 `↑↑↓↓←→←→` 触发 debug 模式 + DebugView 集中展示所有隐藏数据；e2e workflow CI 修复（Node JSON import 兼容、IPv4 binding、onboarding 预设、smoke 适配 v0.1.0）。
- **v1.0** —— **正式发布**：故事书导出（Markdown/EPUB）、世界 JSON 导入导出、模板库扩到 8 套、AI 辅助世界生成器、代码签名、macOS Universal、Linux 包。
- **v1.1+** —— 多人合作、TTS / STT 语音、Discord bot、iOS/Android 客户端等（玩家驱动）。

详见 [长线路线图](docs/superpowers/plans/2026-04-29-roadmap.md)。

## Project layout

```
dzmm/
├── backend/                Python FastAPI + Ollama/cloud LLM client
│   ├── src/dzmm/
│   ├── tests/              130+ pytest tests
│   ├── dzmm-backend.spec   PyInstaller --onedir spec
│   └── build_sidecar.py    PyInstaller wrapper（被 packaging/build.py 调用）
├── frontend/
│   ├── src/                Vue 3 SPA
│   ├── e2e/                Playwright SSE 冒烟（v0.9）
│   └── src-tauri/          Rust shell + bundle config
├── packaging/              整体打包入口 + 产物落地
│   ├── build.py            一键打包脚本（跨平台）
│   ├── build.ps1           Windows PowerShell 包装
│   └── dist/               打好的 .dmg / setup.exe（gitignored）
├── docs/superpowers/plans/ Implementation plans (v0.1 → v0.9+)
├── .github/workflows/      release.yml + e2e.yml
├── CHANGELOG.md
└── README.md
```

## License

(Pick one — currently unspecified. Personal hobby project; ask before redistributing.)

## Acknowledgements

Built collaboratively with Claude Opus 4.7. Worth flagging because it shaped the architectural decisions (streaming tag parser, structured state tracking, repair/fallback paths).
