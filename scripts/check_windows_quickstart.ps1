param(
    [string]$EngineRoot = $env:LAYA_ENGINE_LIBS
)

$ErrorActionPreference = "Stop"

function Require-Command {
    param([string]$Name, [string]$InstallHint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is required but was not found on PATH. $InstallHint"
    }
}

function Require-File {
    param([string]$Path, [string]$Hint)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing required file: $Path. $Hint"
    }
}

$repoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")

Require-Command -Name "python" -InstallHint "Install Python 3.10+ and reopen PowerShell."
Require-Command -Name "node" -InstallHint "Install Node.js 18+ from https://nodejs.org/ and reopen PowerShell."
Require-Command -Name "npm.cmd" -InstallHint "Install Node.js 18+ from https://nodejs.org/ and reopen PowerShell."

$pythonCheck = @"
import importlib
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ is required")
for name in ["fastapi", "uvicorn", "cmaes", "skimage", "PIL"]:
    importlib.import_module(name)
print("python dependencies ok")
"@
$pythonCheck | python -

if (-not $EngineRoot) {
    $EngineRoot = Join-Path $env:LOCALAPPDATA "Programs\LayaAirIDE\resources\engine\libs"
}
foreach ($file in @("laya.core.js", "laya.webgl_2D.js", "laya.d3.js", "laya.webgl_3D.js")) {
    Require-File -Path (Join-Path $EngineRoot $file) -Hint "Install LayaAirIDE or set LAYA_ENGINE_LIBS / -EngineRoot to the Laya engine libs directory."
}

foreach ($file in @(
    "examples\fish_laya_project\assets\resources\game.ls",
    "examples\fish_laya_project\assets\resources\model\1504\mat\1504_body.lmat",
    "examples\fish_laya_project\assets\resources\shader\Custom_low.shader",
    "examples\fish_unity_refs\laya_v000_yaw0_pitch0.png",
    "material_fit\laya_capture\runtime_renderer.html",
    "material_fit\laya_capture\persistent_queue_daemon.py"
)) {
    Require-File -Path (Join-Path $repoRoot.Path $file) -Hint "The repository checkout is incomplete."
}

Write-Host "Windows quick start prerequisites OK."
Write-Host "Laya engine libs: $EngineRoot"
