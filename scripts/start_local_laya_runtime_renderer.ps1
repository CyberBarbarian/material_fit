param(
    [Parameter(Mandatory = $true)]
    [string]$AssetProfile,
    [string]$Server = "http://127.0.0.1:8787",
    [string]$ReadyFile = "",
    [int]$HoldMs = 0,
    [switch]$Headed
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$profile = (Resolve-Path -LiteralPath $AssetProfile).Path
$renderer = Join-Path $repoRoot "material_fit\laya_capture\run_runtime_renderer.js"
$engine = Join-Path $repoRoot "vendor\layaair-3.4.0\libs"
$nodeModules = Join-Path $repoRoot "node_modules"

if (-not (Test-Path -LiteralPath (Join-Path $nodeModules "playwright\package.json"))) {
    throw "Playwright is missing. Run scripts\bootstrap.ps1 first."
}

$arguments = @(
    $renderer,
    "--server", $Server,
    "--engineRoot", $engine,
    "--assetProfile", $profile
)
if ($ReadyFile) {
    $arguments += @("--readyFile", $ReadyFile)
}
if ($HoldMs -gt 0) {
    $arguments += @("--holdMs", $HoldMs)
}
if ($Headed) {
    $arguments += @("--headed", "true")
}

$env:NODE_PATH = $nodeModules
Set-Location -LiteralPath $repoRoot
node @arguments
exit $LASTEXITCODE
