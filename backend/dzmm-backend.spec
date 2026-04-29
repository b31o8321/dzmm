# PyInstaller spec for dzmm backend single-file binary.
# Run with: .venv/bin/pyinstaller dzmm-backend.spec
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

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='dzmm-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    target_arch=None,
)
