param(
    [ValidateSet("finetune", "zero_searchable")]
    [string]$Mode,
    [int]$Iterations = 120,
    [double]$TargetScore = 0.98,
    [string]$Optimizer = "pattern16",
    [int]$Width = 900,
    [int]$Height = 700,
    [int]$CapPort = 0,
    [string]$EngineRoot = "",
    [string]$OutputRoot = "",
    [string]$RunName = "",
    [string]$SearchParamSpace = "",
    [string]$InitialParamsOverride = "",
    [double]$MaxRuntimeSec = 0,
    [switch]$Headed
)

$repoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
$repoRootPath = $repoRoot.Path
$args = @(
    "-m", "material_fit.experiments.fish_core_experiment",
    "--mode", $Mode,
    "--iterations", "$Iterations",
    "--target-score", "$TargetScore",
    "--optimizer", $Optimizer,
    "--width", "$Width",
    "--height", "$Height",
    "--cap-port", "$CapPort",
    "--platform-name", "windows"
)
if ($EngineRoot) {
    $args += @("--engine-root", $EngineRoot)
}
if ($OutputRoot) {
    $args += @("--output-root", $OutputRoot)
}
if ($RunName) {
    $args += @("--run-name", $RunName)
}
if ($SearchParamSpace) {
    $args += @("--search-param-space", $SearchParamSpace)
}
if ($InitialParamsOverride) {
    $args += @("--initial-params-override", $InitialParamsOverride)
}
if ($MaxRuntimeSec -gt 0) {
    $args += @("--max-runtime-sec", "$MaxRuntimeSec")
}
if ($Headed) {
    $args += "--headed"
}

Push-Location $repoRootPath
try {
    & python @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
