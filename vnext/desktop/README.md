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

## Windows Host

The Windows desktop app starts the same vNext sidecar and has the same explicit
"局域网玩法" toggle as macOS. On a Windows build machine, first package the
Windows PyInstaller sidecar, then build the native NSIS installer:

```bash
cd vnext/backend
.venv\\Scripts\\python -m pip install -e '.[package]'
.venv\\Scripts\\python ../packaging/build_backend.py
cd ../desktop
npm run tauri:build:windows
```

Windows is a Host, not a separate server product: when LAN gameplay is on, it
advertises the same `_dzmm._tcp` record and only accepts paired
`/api/v2/mobile/*` gameplay requests from the LAN. Management, model and World
operations remain local to the desktop app.
