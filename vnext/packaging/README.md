# vNext packaging

All vNext artifacts use a distinct application identifier and user-data path
until the release matrix is complete. No v0.x installation is overwritten.

## Desktop sidecar

From `vnext/backend`, install the `package` extra, then build the executable:

```bash
.venv/bin/python -m pip install -e '.[package]'
.venv/bin/python ../packaging/build_backend.py
```

The output is the directory `vnext/desktop/src-tauri/backend-runtime/dzmm-next-backend/`
with the `dzmm-next-backend` executable inside it. It bundles the Alembic migration
scripts and migrates the isolated
`DZMM_NEXT_DATA_DIR` before binding the host selected by Tauri. The executable
is intentionally not committed; a packaged `.app` must still pass its own
create/play/archive/recovery acceptance gate.

Build each desktop platform on that platform. The macOS and Windows Tauri apps
ship the same sidecar API and LAN policy; Windows produces an NSIS installer
through `npm run tauri:build:windows` in `vnext/desktop` after this sidecar
build. Do not cross-compile a sidecar: PyInstaller packages its native Python
runtime and the Tauri Host selects `dzmm-next-backend.exe` only on Windows.
