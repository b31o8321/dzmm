# PyInstaller spec for dzmm backend single-file binary.
# Run with: .venv/bin/pyinstaller dzmm-backend.spec
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

src_root = Path('.').resolve() / 'src'

a = Analysis(
    [str(src_root / 'dzmm' / 'main_entry.py')],
    pathex=[str(src_root)],
    binaries=[],
    datas=[],
    hiddenimports=(
        collect_submodules('dzmm')
        + collect_submodules('uvicorn')
        + collect_submodules('keyring.backends')
        + ['anyio._backends._asyncio', 'aiosqlite']
    ),
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'test', 'unittest', 'pydoc', 'doctest'],
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
