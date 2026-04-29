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

## Recommended models

The GM prompt requires the model to emit structured `<narrative>` and
`<state_change>` tags. **Reasoning-tuned models that wrap output in `<think>`
blocks (e.g. deepseek-r1, o1) often skip the format**; even with v0.2's graceful
fallback you'll lose state tracking. Pick a strong instruction-following model:

| Model | Size | Notes |
|---|---|---|
| `qwen2.5:7b` | 7B | Best balance of size and tag compliance for local |
| `qwen2.5:14b` | 14B | Better narrative quality, needs 16GB RAM |
| `llama3.1:8b` | 8B | Solid alternative, slightly looser narrative |
| `gpt-4o-mini` (cloud) | — | Excellent compliance, ~$0.08/hour of play |
| `claude-haiku` (cloud) | — | Excellent compliance, similar cost |
| `deepseek-r1:8b` | 8B | NOT recommended — burns tokens in `<think>` |

For cloud models use the `openai_compat` type with the provider's OpenAI-format
endpoint.

## Storage

- SQLite at `~/.dzmm/dzmm.db`
- API keys in OS keychain via `keyring`
