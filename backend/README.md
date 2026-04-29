# dzmm backend

AI dynamic TRPG text-game backend (v0.1).

## Setup

    cd backend
    python3.11 -m venv .venv  # or python3.13
    source .venv/bin/activate
    pip install -e ".[dev]"

## Test

    pytest -v

## Run dev server

    python scripts/run_dev.py
    # Server on http://127.0.0.1:8765

## Smoke test (requires Ollama)

In one terminal:
    ollama pull qwen2.5:7b
    ollama serve

In another:
    python scripts/run_dev.py

In a third:
    python scripts/smoke.py

## API

- `POST /worlds`, `GET /worlds`, `GET /worlds/{id}`
- `POST /characters`, `GET /characters?world_id=N`, `GET /characters/{id}`
- `POST /model_configs`, `GET /model_configs`, `POST /model_configs/{id}/test`
- `POST /sessions`, `GET /sessions`, `GET /sessions/{id}`
- `POST /sessions/{id}/turn` — SSE stream

## SSE event types

- `narrative` — `{ text }` — append to UI
- `tag` — `{ name, attrs, content }` — handled in UI status panel
- `parse_error` — `{ message }`
- `summarize_error` — `{ message }`
- `done` — `{}`

## Storage

- SQLite at `~/.dzmm/dzmm.db`
- API keys in OS keychain via `keyring`
