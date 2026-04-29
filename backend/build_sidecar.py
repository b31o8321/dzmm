#!/usr/bin/env python3
"""Build the dzmm-backend sidecar binary for the host platform via PyInstaller,
then copy it into Tauri's binaries dir with the correct triple suffix.

Cross-platform: works on macOS, Linux, Windows.

Usage:
    python build_sidecar.py
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path


def host_triple() -> str:
    """Return the Rust target triple Tauri expects in the binary suffix."""
    machine = platform.machine().lower()
    system = platform.system().lower()

    arch_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }
    arch = arch_map.get(machine, machine)

    if system == "darwin":
        return f"{arch}-apple-darwin"
    if system == "windows":
        return f"{arch}-pc-windows-msvc"
    if system == "linux":
        return f"{arch}-unknown-linux-gnu"
    raise SystemExit(f"unsupported platform: {system}/{machine}")


def find_python_in_venv(backend_dir: Path) -> Path:
    """Return the python executable inside backend/.venv (or fall back to sys.executable)."""
    if sys.platform == "win32":
        cand = backend_dir / ".venv" / "Scripts" / "python.exe"
    else:
        cand = backend_dir / ".venv" / "bin" / "python"
    if cand.exists():
        return cand
    return Path(sys.executable)


def main() -> int:
    backend_dir = Path(__file__).resolve().parent
    project_dir = backend_dir.parent
    spec_file = backend_dir / "dzmm-backend.spec"
    if not spec_file.exists():
        print(f"missing spec file: {spec_file}", file=sys.stderr)
        return 2

    py = find_python_in_venv(backend_dir)
    print(f"[1/3] running PyInstaller via {py}")
    rc = subprocess.call(
        [str(py), "-m", "PyInstaller", str(spec_file), "--clean", "--noconfirm"],
        cwd=str(backend_dir),
    )
    if rc != 0:
        print(f"PyInstaller failed (rc={rc})", file=sys.stderr)
        return rc

    triple = host_triple()
    print(f"[2/3] host triple: {triple}")

    bin_name = "dzmm-backend.exe" if sys.platform == "win32" else "dzmm-backend"
    src = backend_dir / "dist" / bin_name
    if not src.exists():
        print(f"missing build output: {src}", file=sys.stderr)
        return 3

    tauri_bin_dir = project_dir / "frontend" / "src-tauri" / "binaries"
    tauri_bin_dir.mkdir(parents=True, exist_ok=True)

    # Tauri externalBin convention: <basename>-<triple>[.exe]
    suffix = ".exe" if sys.platform == "win32" else ""
    dst = tauri_bin_dir / f"dzmm-backend-{triple}{suffix}"
    shutil.copy2(src, dst)
    if sys.platform != "win32":
        dst.chmod(0o755)

    size_mb = dst.stat().st_size / (1024 * 1024)
    print(f"[3/3] ok: {dst} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
