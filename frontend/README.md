# dzmm frontend

Vue 3 + Vite + TypeScript + TailwindCSS + Element Plus.

## Setup

    cd frontend
    npm install

## Dev

In one terminal start the backend:

    cd backend && python scripts/run_dev.py

In another:

    cd frontend && npm run dev

Open http://localhost:5173.

The Vite dev server proxies `/api/*` to the backend at `http://127.0.0.1:8765`.

## Build

    npm run build

Output in `frontend/dist/`.

## Test

    npm run test

## Routes

- `/sessions` — list saves and start new ones
- `/worlds` — manage world settings (markdown)
- `/characters` — manage characters
- `/models` — manage model configs (Ollama / OpenAI-compatible)
- `/play/:id` — gameplay screen

## Tauri (desktop)

Prereqs: Rust toolchain (`rustup`), backend running separately.

    npm run tauri:dev    # opens native window, hot-reloads frontend
    npm run tauri:build  # produces native installer in src-tauri/target/release/bundle/

The Tauri shell loads the Vite dev server in dev and `dist/` in build. The
Python backend is **not** bundled in v0.1 — start it manually before launching
Tauri (`cd backend && python scripts/run_dev.py`). v0.2 will bundle it as a
PyInstaller sidecar.
