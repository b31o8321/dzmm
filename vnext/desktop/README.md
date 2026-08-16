# DZMM Next desktop

The Phase 1 desktop surface is a clean Vue application that uses API v2 only.
It owns the minimal authoring and recovery flow: create a world, confirm its
first Run, play a turn, and reopen the active Run after refresh. Tauri host
packaging is introduced in a later release phase.

```bash
npm install
npm run dev
```

By default Vite proxies `/api` to `http://127.0.0.1:8765`. For a packaged host,
set `VITE_API_BASE=http://127.0.0.1:8765/api/v2`.
