param(
    [string]$RunName = "",
    [string]$OutputRoot = "",
    [int]$SettleFrames = 0
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$arguments = @("-m", "material_fit.experiments.fish_visual_contract_experiment")
if ($RunName) { $arguments += @("--run-name", $RunName) }
if ($OutputRoot) { $arguments += @("--output-root", $OutputRoot) }
$arguments += @("--settle-frames", "$SettleFrames")
& python @arguments
exit $LASTEXITCODE
