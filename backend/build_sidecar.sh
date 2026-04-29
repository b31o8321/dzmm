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

# Copy into Tauri backend-runtime dir (lib.rs reads from here at runtime)
TAURI_RUNTIME_DIR="../frontend/src-tauri/backend-runtime"
mkdir -p "$TAURI_RUNTIME_DIR"

SRC="dist/dzmm-backend"
cp -r "$SRC/." "$TAURI_RUNTIME_DIR/"
chmod +x "$TAURI_RUNTIME_DIR/dzmm-backend"

echo "ok: $TAURI_RUNTIME_DIR"
