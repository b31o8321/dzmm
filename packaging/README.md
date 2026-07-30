# 打包目录

把整体打包流程集中在这里，最终产物落在 `packaging/dist/`。

## 一键打包

```bash
# macOS / Linux
python packaging/build.py

# macOS 内部验收包：完整 ad-hoc 封装签名，可做 codesign 完整性检查
python packaging/build.py --adhoc-sign

# Windows（PowerShell）
.\packaging\build.ps1
```

`build.py` 是跨平台脚本，依次完成：
1. 检查 `python` / `node` / `cargo`
2. 必要时给 `backend/` 建 venv 并 `pip install -e .[dev]`
3. 必要时跑 `npm install`
4. `backend/build_sidecar.py`：PyInstaller `--onedir` 打 `dzmm-backend` → `frontend/src-tauri/backend-runtime/`
5. `frontend/`：`npm run tauri:build`（Rust release）
6. 把 `frontend/src-tauri/target/release/bundle/{dmg,nsis,msi,deb,appimage}/*` 拷到 `packaging/dist/`

`--adhoc-sign` 只用于 macOS 内部验收。它会 seal app bundle resources，
因此 `codesign --verify --deep --strict` 可以检查包完整性，但它不等同于
Developer ID 签名或 Apple 公证，Gatekeeper 仍会拒绝该测试包。

## 单独运行某一段

```bash
# 只重打后端 sidecar（约 30 秒）
backend/.venv/bin/python backend/build_sidecar.py

# 只跑 tauri build（沿用上次的 backend-runtime/，约 1-3 分钟）
cd frontend && npm run tauri:build
```

## 产出物去向

| 平台 | 文件 | 路径 |
|---|---|---|
| macOS arm64 | `dzmm_x.y.z_aarch64.dmg` | `packaging/dist/` |
| macOS arm64 | `dzmm.app/`（运行时拷贝） | `packaging/dist/` |
| Windows x64 | `dzmm_x.y.z_x64-setup.exe` | `packaging/dist/` |
| Linux x64 | `*.deb` / `*.AppImage` | `packaging/dist/` |

`packaging/dist/` 已 gitignore，不会进 git。

## CI 打包

`.github/workflows/release.yml` 在推 `v*` tag 时自动打 macOS DMG + Windows NSIS，跑 artifact smoke check（v0.9 加），通过后发 GitHub Release。
本地脚本只是给开发者验证用的，CI 才是发版唯一来源。

## 依赖

| 工具 | macOS | Windows |
|---|---|---|
| Python 3.11+ | `brew install python@3.13` | `winget install Python.Python.3.13` |
| Node 18+ | `brew install node` | `winget install OpenJS.NodeJS` |
| Rust stable | `brew install rust` | `winget install Rustlang.Rustup; rustup default stable-x86_64-pc-windows-msvc` |
| MSVC 链接器 | — | `winget install Microsoft.VisualStudio.2022.BuildTools` |
| Ollama（运行时） | `brew install ollama` | `winget install Ollama.Ollama` |
