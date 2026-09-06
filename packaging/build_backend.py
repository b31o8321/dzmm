#!/usr/bin/env python3
"""Build the standalone vNext backend used by the Tauri host."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
RUNTIME = ROOT / "desktop" / "src-tauri" / "backend-runtime"
ENTRYPOINT = Path(__file__).with_name("sidecar_entry.py")
RETIRED_MIGRATION_MARKERS = ("pairing", "remote", "confirmation")


def _available_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def smoke_test(output: Path, data_dir: Path) -> None:
    executable = output / ("dzmm-backend.exe" if os.name == "nt" else "dzmm-backend")
    port = _available_loopback_port()
    environment = os.environ.copy()
    environment.update(
        DZMM_DATA_DIR=str(data_dir),
        DZMM_PORT=str(port),
    )
    process = subprocess.Popen(
        [str(executable)],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"packaged backend exited with code {process.returncode}")
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=0.5
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("app") == "dzmm" and payload.get("storage") == "local":
                    return
                raise RuntimeError(f"unexpected packaged backend health response: {payload}")
            except OSError:
                time.sleep(0.25)
        raise RuntimeError("packaged backend did not become healthy within 30 seconds")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def stage_migrations(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )


def verify_clean_migrations(output: Path) -> None:
    migrations = output / "_internal" / "migrations"
    offenders = [
        path.relative_to(output)
        for path in migrations.rglob("*")
        if path.is_file()
        and (
            "__pycache__" in path.parts
            or path.suffix in {".pyc", ".pyo"}
            or any(marker in path.name.lower() for marker in RETIRED_MIGRATION_MARKERS)
        )
    ]
    if offenders:
        joined = ", ".join(str(path) for path in offenders)
        raise RuntimeError(f"retired migration artifacts entered the runtime: {joined}")


def main() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    output = RUNTIME / "dzmm-backend"
    if output.is_dir():
        shutil.rmtree(output)
    elif output.exists():
        output.unlink()
    with tempfile.TemporaryDirectory(prefix="dzmm-pyinstaller-") as temp_dir:
        temporary = Path(temp_dir)
        staged_migrations = temporary / "migrations"
        stage_migrations(BACKEND / "migrations", staged_migrations)
        # The repo also contains the legacy backend whose package is also named
        # `dzmm`; a leaked PYTHONPATH would let the legacy tree shadow this one
        # during module analysis, so the packaging subprocess runs without it.
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onedir",
                "--name",
                "dzmm-backend",
                "--paths",
                str(BACKEND / "src"),
                # The shared core exposes desktop services through lazy imports so
                # Android can import the pure command engine without FastAPI or
                # SQLAlchemy. PyInstaller cannot discover those import_module calls
                # statically, so collect the package as a single runtime boundary.
                "--collect-submodules",
                "dzmm",
                "--hidden-import",
                "aiosqlite",
                "--collect-submodules",
                "keyring.backends",
                "--add-data",
                f"{BACKEND / 'alembic.ini'}{os.pathsep}.",
                "--add-data",
                f"{staged_migrations}{os.pathsep}migrations",
                "--add-data",
                f"{ROOT / 'contracts'}{os.pathsep}contracts",
                "--distpath",
                str(RUNTIME),
                "--workpath",
                str(temporary / "work"),
                "--specpath",
                str(temporary / "spec"),
                str(ENTRYPOINT),
            ],
            env=environment,
        )
        verify_clean_migrations(output)
        smoke_test(output, temporary / "smoke-data")


if __name__ == "__main__":
    main()
