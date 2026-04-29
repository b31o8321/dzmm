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

### macOS / Linux

```bash
cd backend
.venv/bin/python build_sidecar.py    # produces frontend/src-tauri/backend-runtime/

cd ../frontend
npm run tauri:build                  # produces .dmg
```

Output: `frontend/src-tauri/target/release/bundle/dmg/dzmm_x.y.z_*.dmg`

### Windows

Open PowerShell from the repo root:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\build_windows.ps1
```

Output: `frontend\src-tauri\target\release\bundle\nsis\dzmm_x.y.z_x64-setup.exe`

### CI

Pushing a `v*` tag (e.g. `v0.7`) triggers `.github/workflows/release.yml` which builds both platforms in parallel and publishes a GitHub Release.

## Roadmap

See [docs/superpowers/plans/](docs/superpowers/plans/) for the full plan history. The next focus:

- **v0.7** — Game enjoyment: quest journal, **NPC 攻略详情**（多维好感度 / 动机 / 人设原型 / 互动时间线 / 浏览所有 NPC）, character XP/levelup, BGM + sound effects, character portraits. Plus recursive summary compression and model warmup.
- **v0.8** — Sharing/creator tools: world JSON import/export, AI-assisted world generator, story export to Markdown/EPUB, NPC relationship graph.
- **v0.9+** — Multiplayer co-op, TTS/STT voice, Discord bot.

## Project layout

```
dzmm/
├── backend/                Python FastAPI + Ollama/cloud LLM client
│   ├── src/dzmm/
│   ├── tests/              60+ pytest tests
│   ├── dzmm-backend.spec   PyInstaller --onedir spec
│   └── build_sidecar.py    cross-platform PyInstaller wrapper
├── frontend/
│   ├── src/                Vue 3 SPA
│   └── src-tauri/          Rust shell + bundle config
├── docs/superpowers/plans/ Implementation plans (v0.1 → v0.7+)
├── .github/workflows/      release.yml — matrix build for macOS+Windows
├── build_windows.ps1       PowerShell one-shot Windows build
├── CHANGELOG.md
└── README.md
```

## License

(Pick one — currently unspecified. Personal hobby project; ask before redistributing.)

## Acknowledgements

Built collaboratively with Claude Opus 4.7. Worth flagging because it shaped the architectural decisions (streaming tag parser, structured state tracking, repair/fallback paths).
