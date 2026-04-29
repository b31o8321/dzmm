#!/usr/bin/env bash
# Build the dzmm-backend sidecar binary for the host platform and copy it
# into Tauri's expected location with the platform-triple suffix.
set -euo pipefail

cd "$(dirname "$0")"

. /Users/norman/development/dzmm/backend/.venv/bin/activate 2>/dev/null || true

# Run PyInstaller from the shared venv
/Users/norman/development/dzmm/backend/.venv/bin/pyinstaller dzmm-backend.spec --clean --noconfirm

# Determine target triple suffix that Tauri expects
RUST_TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
echo "host triple: $RUST_TRIPLE"

# Copy into Tauri binaries dir
TAURI_BIN_DIR="../frontend/src-tauri/binaries"
mkdir -p "$TAURI_BIN_DIR"

SRC="dist/dzmm-backend"
DST="${TAURI_BIN_DIR}/dzmm-backend-${RUST_TRIPLE}"
cp "$SRC" "$DST"
chmod +x "$DST"

echo "ok: $DST"
