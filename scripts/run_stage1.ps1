param(
    [ValidateSet("fish", "turtle", "crocodile")]
    [string]$Asset = "fish",
    [int]$Iterations = 1499,
    [double]$TargetScore = 0.995,
    [double]$SuccessScore = 0.98,
    [double]$MaxRuntimeSec = 1200,
    [double]$SpeedGateMs = 500,
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing .venv. Run scripts\bootstrap.ps1 first."
}

$arguments = @(
    "-m", "material_fit.experiments.material_human_reference_stage1",
    "--asset", $Asset,
    "--optimizer", "material_discrete_joint",
    "--joint-profile", "v86_budget1500_initial_score_routed_unified",
    "--iterations", $Iterations,
    "--target-score", $TargetScore,
    "--success-score", $SuccessScore,
    "--max-runtime-sec", $MaxRuntimeSec,
    "--speed-gate-ms", $SpeedGateMs,
    "--node-modules", (Join-Path $repoRoot "node_modules"),
    "--engine-libs", (Join-Path $repoRoot "vendor\layaair-3.4.0\libs")
)
if ($OutputRoot) {
    $arguments += @("--output-root", $OutputRoot)
}

Set-Location -LiteralPath $repoRoot
& $python @arguments
exit $LASTEXITCODE
