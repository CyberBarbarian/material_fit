param(
    [string]$RunDir = "",
    [string]$Material = "",
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing .venv. Run scripts\bootstrap.ps1 first."
}
if (-not $RunDir -and -not $Material) {
    $Material = Join-Path $repoRoot "material_fit\assets\material_starts\1613\experimental_best_20260723.lmat"
}
if (-not $Output) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $Output = Join-Path $repoRoot "artifacts\deliverables\1613_result_$stamp.zip"
}

$arguments = @(
    "-m", "material_fit.experiments.material_delivery_package",
    "--asset", "1613",
    "--output", $Output
)
if ($RunDir) {
    $arguments += @("--run-dir", $RunDir)
}
if ($Material) {
    $arguments += @("--material", $Material)
}
Set-Location -LiteralPath $repoRoot
& $python @arguments
exit $LASTEXITCODE
