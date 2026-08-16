# vNext packaging

All vNext artifacts use a distinct application identifier and user-data path
until the release matrix is complete. No v0.x installation is overwritten.

## Desktop sidecar

From `vnext/backend`, install the `package` extra, then build the executable:

```bash
.venv/bin/python -m pip install -e '.[package]'
.venv/bin/python ../packaging/build_backend.py
```

The output is `vnext/desktop/src-tauri/backend-runtime/dzmm-next-backend`.
It bundles the Alembic migration scripts and migrates the isolated
`DZMM_NEXT_DATA_DIR` before binding the host selected by Tauri. The executable
is intentionally not committed; a packaged `.app` must still pass its own
create/play/archive/recovery acceptance gate.
