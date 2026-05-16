# dzmm

An AI-driven TRPG (tabletop role-playing game) text adventure that runs entirely on your own machine. The GM is a local or cloud LLM; you bring the world, the character, and the imagination. No subscription, no other players needed.

> **中文说明** → [README.zh.md](README.zh.md)

> **Status:** Active · current release **v0.11.0** (open-world runtime + Phase C eval JSONL export). See [CHANGELOG](CHANGELOG.md) for the full history.
>
> All backend Python files carry detailed Chinese comments aimed at readers who know Python syntax but not FastAPI / SQLAlchemy / system architecture. See [docs/learning/](docs/learning/) for guided reading paths.

---

## What it does

- **Multi-agent stateful GM (v0.10)** — the GM is split into a **Director** agent (long-term plot decisions, runs every 5 turns or on key events), a **Scene** agent (narrative + dice + state, streamed each turn), and **per-NPC** agents (each with its own stateful conversation history, so dialogue stays in character). Solves the classic "single LLM mixes up NPCs" + "tries to balance long-term plot and short-term scene = bad rhythm" problems.
- **Scene topology (v0.10)** — explicit `LocationEdge` graph (contains / adjacent / connects / blocked) prevents spatial drift like "实验室 was under the monastery, then a few turns later we walk *out of* the monastery back to the lab". GM is forced to declare relationships when first introducing a location.
- **Wizard-based world + character creation** — 6-step guided LLM generation (world brief → world detail → character → NPC cast → screenplay outline → review). Each step is independently editable and regeneratable.
- **Auto-generated screenplay on first turn** — the GM receives a chapter-structured outline (main events, optional branches, main characters, ending condition) from turn 1, keeping the story coherent from the start.
- **Streaming narrative** — text appears word-by-word, exactly like a real GM typing.
- **Structured state tracking** — HP / sanity / inventory / NPC favor / moods auto-updated from XML-like tags the GM emits (`<state_change>`, `<npc_update>`, `<pc_goal>`, `<pc_mood>`, …).
- **Scene & NPC location tracking** — the GM records which location the PC is in, which NPCs are present, and what items exist in the scene. NPCs are cleared from a scene when they leave.
- **NPC proactive behavior** — after a few turns of silence, NPCs with high eagerness scores will automatically reach out to the PC (no player input needed), keeping the world alive.
- **Plot threads** — quests, hooks, and major events are tracked and re-injected into future prompts so the campaign stays coherent.
- **RAG world book retrieval** — large world books are split into chunks and stored in a local vector database (ChromaDB). Each turn retrieves only the most relevant chunks, reducing prompt size for 7B models.
- **Screenplay-driven pacing** — the GM is gently forced to advance main events every 1-2 turns; a "plot push" warning appears in key_facts when stalled.
- **Dice system** — d20 + DC checks (standard mode); failures produce real consequences, not "nothing happens".
- **Phone / tablet access** — opt-in LAN mode lets you play on any device on the same WiFi.
- **Export** — download the full session as JSON or Markdown.

---

## Quick start

### Option A: prebuilt app (recommended)

1. Install [Ollama](https://ollama.com/download), then pull a model:
   ```bash
   ollama pull qwen2.5:7b
   ```
2. Download the latest release from [Releases](https://github.com/YOUR_USERNAME/dzmm/releases):
   - **macOS (Apple Silicon)**: `dzmm_x.y.z_aarch64.dmg`
   - **Windows x64**: `dzmm_x.y.z_x64-setup.exe`
3. Install and launch. First time on macOS: right-click → Open (Gatekeeper warning).
4. Click **跑团 → + 新开一局**. Four preset worlds are included — pick one and play.

### Option B: dev from source

Requirements: Python 3.11+, Node 18+, Rust stable, Ollama.

```bash
git clone https://github.com/YOUR_USERNAME/dzmm.git
cd dzmm

# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Frontend
cd ../frontend && npm install

# Run (3 terminals)
# 1) ollama serve
# 2) cd backend && python scripts/run_dev.py
# 3) cd frontend && npm run dev
```

Open http://localhost:5173.

---

## Recommended models

The GM prompt uses structured XML-like tags. Models that produce heavy reasoning tokens (`<think>` blocks) or ignore format instructions will struggle.

| Model | Size | Notes |
|---|---|---|
| `qwen2.5:7b` | 4.7 GB | **Best balance** for local — solid tag compliance |
| `qwen2.5:14b` | 9 GB | Better narrative depth; needs ≥16 GB RAM |
| `llama3.1:8b` | 4.7 GB | Good alternative |
| `gpt-4o-mini` (cloud) | — | Excellent compliance, ~$0.08 / hour of play |
| `claude-haiku-4` (cloud) | — | Excellent compliance, similar cost |

Cloud models use the `openai_compat` config type — works with OpenAI, Anthropic (via proxy), DeepSeek, Doubao, Tongyi, 零一万物, or anything with an OpenAI-shaped API.

---

## Architecture overview

```
┌──────────────────────────────────────────────┐
│  Tauri 2 shell (Rust)                        │
│  • Spawns backend sidecar on launch          │
│  • Hosts webview for frontend                │
│  • Kills backend on window close             │
└─────────────────┬────────────────────────────┘
                  │
      ┌───────────▼──────────────┐    ┌────────────────────┐
      │ FastAPI backend (:8765)  │───▶│  Ollama / cloud LLM│
      │  /sessions/{id}/turn     │    └────────────────────┘
      │  SSE streaming           │
      │  SQLite persistence      │
      │  tag-based state apply   │
      └───────────┬──────────────┘
                  ▲
                  │ axios + fetch (SSE)
      ┌───────────┴──────────────┐
      │ Vue 3 + Vite frontend    │
      │  streaming parser        │
      │  Element Plus UI         │
      │  Pinia state stores      │
      └──────────────────────────┘
```

- **Backend:** Python 3.11+ · FastAPI · SQLAlchemy 2.0 async · aiosqlite
- **Frontend:** Vue 3 · TypeScript · Element Plus · Tailwind CSS · Pinia
- **Desktop:** Tauri 2 (Rust shell, ~5 MB) + PyInstaller-bundled backend (~45 MB)
- **Storage:** SQLite at `~/.dzmm/dzmm.db`; logs at `~/.dzmm/dzmm.log` (5 MB × 3 rotation); API keys in OS keychain

For a deeper technical walkthrough see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## LAN / phone access

In the app's welcome dialog choose **启用手机访问**. The backend will bind to `0.0.0.0:8765` and display your LAN URL. Type that URL into your phone's browser — both devices must be on the same WiFi network.

> Don't enable on untrusted networks (cafes, etc.) — the backend has no auth.

---

## Building from source

```bash
# macOS / Linux
python packaging/build.py

# Windows (PowerShell)
.\packaging\build.ps1
```

Output lands in `packaging/dist/`. For partial rebuilds (backend only, or reusing an existing backend runtime) see [packaging/README.md](packaging/README.md).

A `v*` tag push (e.g. `v0.2.7`) triggers `.github/workflows/release.yml`, which builds macOS and Windows in parallel and publishes a GitHub Release.

---

## Project layout

```
dzmm/
├── backend/
│   ├── src/dzmm/
│   │   ├── api/routes_sessions/   per-resource route modules
│   │   ├── db/                    ORM models + migrations
│   │   ├── service/               game loop, state_apply handlers, NPC initiative
│   │   ├── prompts/               GM template, outliner, summarizer, wizard prompts
│   │   └── parsing/               streaming tag parser
│   └── tests/                     346+ pytest tests
├── frontend/src/
│   ├── views/                     GameView, SessionsView, WizardView, …
│   ├── components/                MessageList, StatePanel, SpeakerBubble, …
│   ├── composables/               useGameTurn, useTurnStream, useGameState, …
│   ├── api/                       typed API clients
│   └── stores/                    Pinia stores
├── packaging/                     build orchestration
├── docs/
│   ├── ARCHITECTURE.md
│   └── superpowers/plans/         implementation plans
├── CHANGELOG.md
└── README.md  ←  you are here
```

---

---

## Learning docs

All backend Python files carry detailed Chinese inline comments (targeting readers who know Python syntax but not FastAPI / SQLAlchemy / architecture). Companion docs live in [`docs/learning/`](docs/learning/):

| Doc | Contents |
|-----|----------|
| [**Code reading path**](docs/learning/code-reading-path.md) | **Start here:** 7-stage guided walkthrough from boot to multi-agent |
| [Python backend](docs/learning/python-backend.md) | async/await, SQLAlchemy, FastAPI, migrations |
| [LLM engineering](docs/learning/llm-engineering.md) | Prompt design, streaming parsing, context management |
| [Vue 3 frontend](docs/learning/vue-frontend.md) | SSE, Composables, Pinia, reactivity |
| [Phase A: LangChain RAG](docs/learning/langchain-rag.md) | OllamaEmbedder, ChromaDB, graceful degradation |
| [Phase B: LangGraph multi-agent](docs/learning/langgraph-multiagent.md) | StateGraph, conditional edges, multi-agent orchestration |
| [Phase C: autonomous eval](docs/learning/agent-eval.md) | LLM-as-Judge, Player Agent, Judge Agent |
| [TRPG LLM optimisation](docs/learning/trpg-llm-optimization.md) | RAG / multi-agent / rules / dice / streaming in practice |

---

## Implemented technical evolution

**Phase A — LangChain RAG world-book retrieval** ✅
- OllamaEmbedder + ChromaDB + RecursiveCharacterTextSplitter
- Large world books auto-chunked; top-k relevant chunks injected per turn

**Phase B — LangGraph multi-agent GM** ✅ (v0.10)
- Director (strategy) / Scene (narrative) / NPC Actors / Orchestrator
- StateGraph, conditional edges, closure injection, persistent AgentStream/AgentMessage

**Phase C — autonomous evaluation** ✅ (complete in v0.11.0)
- Player Agent auto-plays sessions from character_md + recent history
- Judge Agent (LLM-as-Judge) scores plot_speed / rule_violations / rp_immersion / dice_accuracy
- Eval runner: A/B compare, Markdown report + JSONL training data export
- CLI: `python -m dzmm.eval.cli --session-id N --turns 20 --export-jsonl train.jsonl`

**v0.11 open-world framework** ✅ (runtime complete in v0.11.0)
- WorldFramework: locations / factions / NPC templates / events / Campaign phases
- Director reads "nearby available events × BFS distance × main-plot progress"
- WorldMapPanel SVG topology view, CampaignProgressPanel phase tracking
- Event state machine (pending → triggered → completed) + auto Campaign phase advance

## Planned but unimplemented

**Phase D — QLoRA fine-tuning**
- Use the JSONL training data exported from Phase C to fine-tune a TRPG-specialist small model
- Target: 7B model matching GPT-4o-mini on TRPG tag-compliance
- Hardware: desktop Linux + RX 9070

**v0.14 screenplay-driven overhaul** (larger rework)
- On session start, one LLM call generates a full screenplay outline (chapters / key NPCs / key events / ending condition)
- GM narrates *within* the outline rather than improvising the main plot from scratch
- Player pivotal decisions emit `<plot_turn>` → backend asynchronously rewrites the remaining outline
- After the ending, players can continue (Season 2) or start fresh from a genre template

---

## License

Personal hobby project — currently unspecified. Ask before redistributing.

## Acknowledgements

Built collaboratively with Claude (Anthropic). The streaming tag parser, structured state-apply dispatch, and screenplay-driven GM prompt design all emerged from that collaboration.
