# vNext packaging

All vNext artifacts use a distinct application identifier and user-data path
until the release matrix is complete. No v0.x installation is overwritten.

## Desktop sidecar

From `vnext/backend`, install the `package` extra, then build the executable:

```bash
.venv/bin/python -m pip install -e '.[package]'
.venv/bin/python ../packaging/build_backend.py
```

The output is the directory `vnext/desktop/src-tauri/backend-runtime/dzmm-backend/`
with the `dzmm-backend` executable inside it. It bundles the Alembic migration
scripts and migrates the isolated
`DZMM_DATA_DIR` before binding the loopback host. The executable is
intentionally not committed. The build command starts the frozen executable against
temporary data and requires a valid local `/health` response, which guards lazy shared-core
imports and migration packaging; a packaged `.app` must still pass its own
create/play/archive/recovery acceptance gate.

Migration files are copied through a clean staging directory before PyInstaller runs.
`__pycache__`, bytecode, and retired pairing/remote/confirmation migrations are rejected
from the runtime so deleted preview behavior cannot survive inside a newly built installer.

Build each desktop platform on that platform. The macOS and Windows Tauri apps
ship the same loopback sidecar API; Windows produces an NSIS installer
through `npm run tauri:build:windows` in `vnext/desktop` after this sidecar
build. Do not cross-compile a sidecar: PyInstaller packages its native Python
runtime and the Tauri Host selects `dzmm-backend.exe` only on Windows.
