# DZMM Next Preview

This is a clean product root for DZMM vNext. It intentionally has no import
path to the legacy application and defaults to a separate `~/.dzmm-vnext-v3/`
data directory. Schema v3 intentionally starts fresh rather than opening or
migrating preview schema-v2 worlds; the sidecar rejects an explicitly supplied
previous-preview directory after its metadata check.

Phase 0 provides the contracts, fresh database baseline, API v2 health check,
and scorecard harness. It is not yet a playable game.

## Layout

- `backend/`: FastAPI host, fresh schema and Alembic migrations.
- `contracts/`: versioned JSON Schemas shared by clients and server.
- `desktop/`: Tauri/Vue Local Host shell for macOS and Windows.
- `mobile/`: Flutter Android Local Host. It owns app-private SQLite and calls the shared Python
  core and selected model provider directly; it never requires a PC Host.
- `eval/`: evidence-first maturity scorecard.
- `packaging/`: vNext-only release assembly.

## Phase 0 verification

```bash
cd vnext/backend
python -m alembic upgrade head
python -m pytest -q
python ../eval/scorecard.py ../eval/evidence/phase0.json
```
