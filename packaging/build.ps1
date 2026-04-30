# dzmm Windows 整体打包入口（PowerShell 包装 build.py）
# 用法（仓库根目录）：
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
#   .\packaging\build.ps1
#
# 等价的纯 Python 调用（已经手动装好 venv 时）：
#   python packaging\build.py
#
# 一次性安装的前置依赖：
#   winget install Python.Python.3.13
#   winget install OpenJS.NodeJS
#   winget install Rustlang.Rustup
#   rustup default stable-x86_64-pc-windows-msvc
#   winget install Microsoft.VisualStudio.2022.BuildTools  # MSVC linker
#   winget install Ollama.Ollama

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "repo root: $repoRoot" -ForegroundColor Cyan
Push-Location $repoRoot
try {
    python "$PSScriptRoot\build.py" @args
} finally {
    Pop-Location
}

$dist = Join-Path $PSScriptRoot "dist"
$exe = Get-ChildItem -Path $dist -Filter "*-setup.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($exe) {
    Write-Host ""
    Write-Host "安装包: $($exe.FullName)" -ForegroundColor Green
    Write-Host "大小:   $([math]::Round($exe.Length / 1MB, 1)) MB"
}
