param(
    [string]$Server = "http://127.0.0.1:8787",
    [int]$Width = 320,
    [int]$Height = 240,
    [string]$ProjectRoot = "",
    [string]$Scene = "",
    [string]$EngineRoot = $env:LAYA_ENGINE_LIBS,
    [string]$ReadyFile = "",
    [int]$HoldMs = 0,
    [switch]$DebugMaterial,
    [switch]$Headed
)

function Require-Command {
    param([string]$Name, [string]$InstallHint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Error "$Name is required but was not found on PATH. $InstallHint"
        exit 2
    }
}

$repoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
$workDir = Join-Path $repoRoot.Path "artifacts\real_laya_run"
$nodeModules = Join-Path $workDir "node_modules\playwright-chromium"
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

Require-Command -Name "node" -InstallHint "Install Node.js 18+ from https://nodejs.org/ and reopen PowerShell."
Require-Command -Name "npm.cmd" -InstallHint "Install Node.js 18+ from https://nodejs.org/ and reopen PowerShell."
Require-Command -Name "python" -InstallHint "Install Python 3.10+ and ensure python.exe is on PATH."

if (-not $EngineRoot) {
    $EngineRoot = Join-Path $env:LOCALAPPDATA "Programs\LayaAirIDE\resources\engine\libs"
}
$requiredEngineFiles = @("laya.core.js", "laya.webgl_2D.js", "laya.d3.js", "laya.webgl_3D.js")
foreach ($file in $requiredEngineFiles) {
    $path = Join-Path $EngineRoot $file
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Error "Laya engine file is missing: $path. Install LayaAirIDE or set LAYA_ENGINE_LIBS / -EngineRoot to the directory containing Laya engine libs."
        exit 2
    }
}

if (-not (Test-Path $nodeModules)) {
    Push-Location $workDir
    try {
        if (-not (Test-Path "package.json")) {
            npm.cmd init -y | Out-Null
        }
        npm.cmd install playwright-chromium --no-save
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    } finally {
        Pop-Location
    }
}

$env:NODE_PATH = Join-Path $workDir "node_modules"
$renderer = Join-Path $repoRoot.Path "material_fit\laya_capture\run_runtime_renderer.js"
$args = @(
    $renderer,
    "--server", $Server,
    "--width", "$Width",
    "--height", "$Height",
    "--engineRoot", $EngineRoot
)
if ($ProjectRoot) {
    $args += @("--projectRoot", $ProjectRoot)
}
if ($Scene) {
    $args += @("--scene", $Scene)
}
if ($ReadyFile) {
    $args += @("--readyFile", $ReadyFile)
}
if ($HoldMs -gt 0) {
    $args += @("--holdMs", "$HoldMs")
}
if ($DebugMaterial) {
    $args += @("--debugMaterial", "true")
}
if ($Headed) {
    $args += @("--headed", "true")
}
node @args
