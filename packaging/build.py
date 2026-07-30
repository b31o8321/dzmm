#!/usr/bin/env python3
"""dzmm 整体打包入口（跨平台）。

流程：
  1. 检查 python / node / cargo
  2. 用 backend 的 venv 跑 PyInstaller 产出 backend-runtime/
  3. 跑 frontend 的 tauri build 产出 .dmg / .app / _setup.exe
  4. 把最终产物拷到 packaging/dist/

用法：
    python packaging/build.py            # 默认走 release
    python packaging/build.py --debug    # tauri build --debug
    python packaging/build.py --adhoc-sign  # macOS 内部验收签名

最终产物路径：packaging/dist/
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"
DIST_DIR = REPO_ROOT / "packaging" / "dist"
BUNDLE_DIR = FRONTEND_DIR / "src-tauri" / "target" / "release" / "bundle"


def check(cmd: str, hint: str) -> None:
    if shutil.which(cmd) is None:
        print(f"[x] 缺少 {cmd} —— {hint}", file=sys.stderr)
        sys.exit(1)
    print(f"[ok] {cmd}")


def venv_python() -> Path:
    if sys.platform == "win32":
        return BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
    return BACKEND_DIR / ".venv" / "bin" / "python"


def ensure_backend_venv() -> None:
    py = venv_python()
    if py.exists():
        return
    print("[setup] 创建 backend venv 并安装依赖（首次约 1 分钟）")
    subprocess.check_call([sys.executable, "-m", "venv", str(BACKEND_DIR / ".venv")])
    subprocess.check_call([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call(
        [str(py), "-m", "pip", "install", "-e", ".[dev]"],
        cwd=str(BACKEND_DIR),
    )


def ensure_frontend_deps() -> None:
    if (FRONTEND_DIR / "node_modules").is_dir():
        return
    print("[setup] 安装 frontend 依赖（首次约 1-2 分钟）")
    subprocess.check_call(["npm", "install"], cwd=str(FRONTEND_DIR))


def run_pyinstaller() -> None:
    print("\n=== [1/3] PyInstaller 打 backend-runtime ===")
    subprocess.check_call(
        [str(venv_python()), "build_sidecar.py"],
        cwd=str(BACKEND_DIR),
    )


def run_tauri(debug: bool, adhoc_sign: bool) -> None:
    print("\n=== [2/3] Tauri build (Rust release，首次约 3-6 分钟) ===")
    cmd = ["npm", "run", "tauri:build"]
    if debug or adhoc_sign:
        cmd = ["npx", "tauri", "build"]
        if debug:
            cmd.append("--debug")
        if adhoc_sign:
            cmd.extend([
                "--config",
                '{"bundle":{"macOS":{"signingIdentity":"-"}}}',
            ])
    subprocess.check_call(cmd, cwd=str(FRONTEND_DIR))


def collect_artifacts() -> list[Path]:
    """把 tauri 产出的最终包从 bundle/ 拷到 packaging/dist/"""
    print("\n=== [3/3] 收集产物到 packaging/dist/ ===")
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    found: list[Path] = []
    system = platform.system().lower()
    patterns: list[tuple[str, str]] = []
    if system == "darwin":
        patterns = [("dmg", "*.dmg"), ("macos", "*.app")]
    elif system == "windows":
        patterns = [("nsis", "*-setup.exe"), ("msi", "*.msi")]
    elif system == "linux":
        patterns = [("deb", "*.deb"), ("appimage", "*.AppImage")]

    for sub, pat in patterns:
        sub_dir = BUNDLE_DIR / sub
        if not sub_dir.is_dir():
            continue
        for p in sub_dir.glob(pat):
            target = DIST_DIR / p.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            if p.is_dir():
                shutil.copytree(p, target)
            else:
                shutil.copy2(p, target)
            size_mb = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) / (1024 * 1024) \
                if target.is_dir() else target.stat().st_size / (1024 * 1024)
            print(f"  -> {target.relative_to(REPO_ROOT)}  ({size_mb:.1f} MB)")
            found.append(target)

    if not found:
        print("[!] 没找到任何 bundle 产物，检查 tauri build 日志。", file=sys.stderr)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="tauri build --debug")
    parser.add_argument(
        "--adhoc-sign",
        action="store_true",
        help="macOS: seal the internal test app with an ad-hoc signature",
    )
    parser.add_argument("--skip-deps", action="store_true", help="跳过 venv / npm install 检查")
    args = parser.parse_args()
    if args.adhoc_sign and sys.platform != "darwin":
        parser.error("--adhoc-sign is supported only on macOS")

    print("=== 检查依赖 ===")
    check("python3" if sys.platform != "win32" else "python",
          "macOS: brew install python@3.13；Windows: winget install Python.Python.3.13")
    check("node", "winget install OpenJS.NodeJS / brew install node")
    check("cargo", "winget install Rustlang.Rustup / brew install rust")

    if not args.skip_deps:
        ensure_backend_venv()
        ensure_frontend_deps()

    run_pyinstaller()
    run_tauri(debug=args.debug, adhoc_sign=args.adhoc_sign)
    artifacts = collect_artifacts()

    print("\n=== 完成 ===")
    for a in artifacts:
        print(f"  {a}")
    return 0 if artifacts else 1


if __name__ == "__main__":
    sys.exit(main())
