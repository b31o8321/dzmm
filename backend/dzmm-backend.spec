# PyInstaller spec for dzmm backend, --onedir mode.
# Output: dist/dzmm-backend/ (directory with dzmm-backend[.exe] + DLLs/data).
# Run with: .venv/bin/pyinstaller dzmm-backend.spec
#
# We use onedir (not onefile) because:
#   1. --onefile bootloader extracts to %TEMP%/_MEIxxxx/ on every launch.
#      On Chinese-Windows usernames, GetTempPath() returns 8.3-short-name
#      paths that LoadLibrary mishandles → "Failed to load Python DLL".
#   2. Cold start drops from ~25s to ~3s — no extraction, all DLLs already
#      sitting next to the .exe.
# Tauri bundles this whole directory via bundle.resources.
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

src_root = Path('.').resolve() / 'src'

# Explicit imports — keep this list minimal. Each entry has measurable
# cold-start cost. The previous broad collect_submodules('uvicorn') pulled in
# ~hundreds of unused modules; we list only what main_entry actually needs.
hidden = [
    # uvicorn essentials
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.wsproto_impl',
    'uvicorn.logging',
    'uvicorn.config',
    # async sqlite
    'aiosqlite',
    # anyio backend used by FastAPI/SSE
    'anyio._backends._asyncio',
    # SSE
    'sse_starlette',
    'sse_starlette.sse',
]

# Our own package — small and we import all of it anyway.
hidden += collect_submodules('dzmm')

# Keyring backends are platform-specific and resolved at runtime via stevedore-style
# discovery — keep the broad collect for these.
hidden += collect_submodules('keyring.backends')

a = Analysis(
    [str(src_root / 'dzmm' / 'main_entry.py')],
    pathex=[str(src_root)],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter', 'test', 'unittest', 'pydoc', 'doctest',
        'httptools', 'uvloop', 'watchfiles',
        'pydantic.v1', 'pydantic.deprecated',
        'numpy', 'pandas',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# --- onedir mode ---
# EXE holds only the entry executable; binaries/data go through COLLECT.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='dzmm-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,
    console=True,
    target_arch=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=True,
    upx=False,
    name='dzmm-backend',
)
