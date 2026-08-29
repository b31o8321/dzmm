# DZMM desktop

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

## Windows Local Host

The Windows desktop app starts the same local vNext sidecar as macOS. There is
no startup-mode, LAN, pairing or remote-client choice: each desktop app owns
its local SQLite, Python state judge and direct model profiles. On a Windows
build machine, first package the Windows PyInstaller sidecar, then build the
native NSIS installer:

Authenticated provider API Keys are stored in the operating-system keychain;
the local database and portable bundles contain only a reference.

```bash
cd vnext/backend
.venv\\Scripts\\python -m pip install -e '.[package]'
.venv\\Scripts\\python ../packaging/build_backend.py
cd ../desktop
npm run tauri:build:windows
```

Android is another Local Host, not a remote client. Cross-device use will be
explicit portable export/import/clone rather than LAN discovery or shared live
state (ADR-008).
