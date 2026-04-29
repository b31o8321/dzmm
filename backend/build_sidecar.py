#!/usr/bin/env python3
"""Build the dzmm-backend bundle for the host platform via PyInstaller (onedir
mode), then copy the whole directory into the Tauri project so it can be
included via tauri.conf.json:bundle.resources.

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
    print(f"[1/3] running PyInstaller (onedir) via {py}")
    rc = subprocess.call(
        [str(py), "-m", "PyInstaller", str(spec_file), "--clean", "--noconfirm"],
        cwd=str(backend_dir),
    )
    if rc != 0:
        print(f"PyInstaller failed (rc={rc})", file=sys.stderr)
        return rc

    triple = host_triple()
    print(f"[2/3] host triple: {triple}")

    # PyInstaller onedir outputs: dist/dzmm-backend/ (directory)
    src_dir = backend_dir / "dist" / "dzmm-backend"
    if not src_dir.is_dir():
        print(f"missing build output dir: {src_dir}", file=sys.stderr)
        return 3

    # Copy the whole directory into the Tauri tree where bundle.resources
    # can reach it. Replace any prior copy.
    tauri_runtime = project_dir / "frontend" / "src-tauri" / "backend-runtime"
    if tauri_runtime.exists():
        shutil.rmtree(tauri_runtime)
    shutil.copytree(src_dir, tauri_runtime)

    # Verify the entry binary lives where Rust expects it.
    bin_name = "dzmm-backend.exe" if sys.platform == "win32" else "dzmm-backend"
    entry = tauri_runtime / bin_name
    if not entry.exists():
        print(f"entry binary missing after copy: {entry}", file=sys.stderr)
        return 4
    if sys.platform != "win32":
        entry.chmod(0o755)

    total_size = sum(p.stat().st_size for p in tauri_runtime.rglob("*") if p.is_file())
    size_mb = total_size / (1024 * 1024)
    file_count = sum(1 for _ in tauri_runtime.rglob("*"))
    print(f"[3/3] ok: {tauri_runtime} ({size_mb:.1f} MB total, {file_count} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
