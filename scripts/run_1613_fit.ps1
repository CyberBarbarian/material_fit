param(
    [int]$Iterations = 1500,
    [double]$TargetScore = 0.995,
    [double]$MaxRuntimeSec = 1800,
    [string]$ViewIds = "",
    [string]$ObservationManifest = "",
    [string]$StartMaterial = "",
    [string]$OutputRoot = "",
    [string]$RunName = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing .venv. Run scripts\bootstrap.ps1 first."
}

$arguments = @(
    "-m", "material_fit.experiments.material_cross_engine_stage2_multiview_v86",
    "--iterations", $Iterations,
    "--target-score", $TargetScore,
    "--max-runtime-sec", $MaxRuntimeSec,
    "--node-modules", (Join-Path $repoRoot "node_modules")
)
if ($ViewIds) {
    $arguments += @("--view-ids", $ViewIds)
}
if ($ObservationManifest) {
    $arguments += @("--observation-manifest", $ObservationManifest)
}
if ($StartMaterial) {
    $arguments += @("--start-material", $StartMaterial)
}
if ($OutputRoot) {
    $arguments += @("--output-root", $OutputRoot)
}
if ($RunName) {
    $arguments += @("--run-name", $RunName)
}

Set-Location -LiteralPath $repoRoot
& $python @arguments
exit $LASTEXITCODE
