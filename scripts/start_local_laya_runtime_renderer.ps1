param(
    [string]$Server = "http://127.0.0.1:8787",
    [int]$Width = 320,
    [int]$Height = 240,
    [string]$ProjectRoot = "",
    [string]$Scene = "",
    [string]$ReadyFile = "",
    [int]$HoldMs = 0,
    [switch]$Headed
)

$repoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
$workDir = Join-Path $repoRoot.Path "artifacts\real_laya_run"
$nodeModules = Join-Path $workDir "node_modules\playwright-chromium"
New-Item -ItemType Directory -Force -Path $workDir | Out-Null

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
    "--height", "$Height"
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
if ($Headed) {
    $args += @("--headed", "true")
}
node @args
