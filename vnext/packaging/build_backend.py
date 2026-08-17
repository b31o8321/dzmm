#!/usr/bin/env python3
"""Build the standalone vNext backend used by the Tauri host."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
RUNTIME = ROOT / "desktop" / "src-tauri" / "backend-runtime"
ENTRYPOINT = Path(__file__).with_name("sidecar_entry.py")


def main() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    output = RUNTIME / "dzmm-next-backend"
    if output.is_dir():
        shutil.rmtree(output)
    elif output.exists():
        output.unlink()
    with tempfile.TemporaryDirectory(prefix="dzmm-next-pyinstaller-") as temp_dir:
        temporary = Path(temp_dir)
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onedir",
                "--name",
                "dzmm-next-backend",
                "--paths",
                str(BACKEND / "src"),
                "--hidden-import",
                "aiosqlite",
                "--add-data",
                f"{BACKEND / 'alembic.ini'}{os.pathsep}.",
                "--add-data",
                f"{BACKEND / 'migrations'}{os.pathsep}migrations",
                "--add-data",
                f"{ROOT / 'contracts'}{os.pathsep}contracts",
                "--distpath",
                str(RUNTIME),
                "--workpath",
                str(temporary / "work"),
                "--specpath",
                str(temporary / "spec"),
                str(ENTRYPOINT),
            ]
        )


if __name__ == "__main__":
    main()
