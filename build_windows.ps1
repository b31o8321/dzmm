# Build dzmm desktop app on Windows.
# Produces: frontend\src-tauri\target\release\bundle\msi\dzmm_0.1.0_x64.msi
#
# Prerequisites (one-time installs):
#   winget install Python.Python.3.13
#   winget install OpenJS.NodeJS
#   winget install Rustlang.Rustup
#   rustup default stable-x86_64-pc-windows-msvc
#   winget install Microsoft.VisualStudio.2022.BuildTools  (for MSVC linker)
#   winget install Ollama.Ollama
#
# Then in PowerShell from the repo root:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
#   .\build_windows.ps1

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
$backend = Join-Path $repoRoot "backend"
$frontend = Join-Path $repoRoot "frontend"

function Check-Cmd($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "[x] $cmd not found. $hint" -ForegroundColor Red
        exit 1
    }
    Write-Host "[ok] $cmd" -ForegroundColor Green
}

Write-Host "=== checking prereqs ===" -ForegroundColor Cyan
Check-Cmd "python" "install Python 3.11+ from python.org or winget install Python.Python.3.13"
Check-Cmd "node"   "winget install OpenJS.NodeJS"
Check-Cmd "cargo"  "winget install Rustlang.Rustup; rustup default stable"
Check-Cmd "npm"    "comes with Node.js"

Write-Host ""
Write-Host "=== [1/4] backend venv + deps ===" -ForegroundColor Cyan
Push-Location $backend
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

Write-Host ""
Write-Host "=== [2/4] PyInstaller sidecar (~1-2 min) ===" -ForegroundColor Cyan
.\.venv\Scripts\python.exe build_sidecar.py
Pop-Location

Write-Host ""
Write-Host "=== [3/4] frontend deps ===" -ForegroundColor Cyan
Push-Location $frontend
if (-not (Test-Path "node_modules")) {
    npm install
}

Write-Host ""
Write-Host "=== [4/4] tauri build (Rust release + .msi, ~2-4 min first time) ===" -ForegroundColor Cyan
npm run tauri:build
Pop-Location

Write-Host ""
Write-Host "=== done ===" -ForegroundColor Green
$msi = Get-ChildItem -Path "$frontend\src-tauri\target\release\bundle\msi" -Filter "*.msi" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($msi) {
    Write-Host "MSI: $($msi.FullName)" -ForegroundColor Green
    Write-Host "size: $([math]::Round($msi.Length / 1MB, 1)) MB"
} else {
    Write-Host "(MSI not found — check tauri output above)" -ForegroundColor Yellow
}
