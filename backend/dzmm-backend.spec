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
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

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

# Phase A/B: LangChain RAG + LangGraph — these use lazy imports / plugin registries
# that PyInstaller can't trace statically, so broad collect is necessary here.
hidden += collect_submodules('langchain_core')
hidden += collect_submodules('langgraph')
hidden += collect_submodules('langchain_text_splitters')
hidden += collect_submodules('chromadb')
# pydantic.v1 shim required by langchain_core._api.deprecation at import time.
hidden += ['pydantic.v1', 'pydantic.v1.main', 'pydantic.v1.fields']

# edge-tts: pure Python async websocket client
hidden += ['edge_tts', 'edge_tts.communicate', 'edge_tts.exceptions']

# kokoro-onnx: ONNX-based TTS, no torch required.
# numpy + onnxruntime are hard imports of kokoro_onnx — must not be excluded.
# phonemizer + joblib are transitive deps pulled in by kokoro_onnx.tokenizer.
# espeakng_loader ships its own espeak-ng-data directory; must be bundled or
# get_data_path() raises "data path not exists" at runtime.
hidden += collect_submodules('kokoro_onnx')
hidden += collect_submodules('phonemizer')
hidden += collect_submodules('espeakng_loader')
hidden += collect_submodules('joblib')
hidden += collect_submodules('onnxruntime')
hidden += ['numpy', 'soundfile', 'soundfile._soundfile']

# Data files: non-Python assets that packages read at runtime.
# kokoro_onnx reads config.json (get_vocab()) on import.
# phonemizer needs share/ g2p/festival files; language_tags needs JSON registry.
# espeakng_loader needs its bundled espeak-ng-data/ voice/dict files.
# chromadb needs migration SQL files.
# joblib test data excluded (65 files, not needed at runtime).
# cosyvoice_server_script.py runs in the isolated uv venv as a subprocess — bundle it.
datas = [(str(src_root / 'dzmm' / 'tts' / 'cosyvoice_server_script.py'), 'dzmm/tts')]
datas += collect_data_files('kokoro_onnx')
datas += collect_data_files('phonemizer')
datas += collect_data_files('espeakng_loader')
datas += collect_data_files('language_tags')
datas += collect_data_files('chromadb')
datas += [(src, dst) for src, dst in collect_data_files('joblib') if '/test/' not in src]

a = Analysis(
    [str(src_root / 'dzmm' / 'main_entry.py')],
    pathex=[str(src_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter', 'test', 'unittest', 'doctest',
        'httptools', 'uvloop', 'watchfiles',
        'pandas',
        # pydoc removed: joblib (dep of phonemizer/kokoro_onnx) imports it
        # pydantic.v1 removed: langchain_core._api.deprecation requires it
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
