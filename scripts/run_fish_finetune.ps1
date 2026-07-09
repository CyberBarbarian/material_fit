param(
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

$args = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", "$PSScriptRoot\run_fish_core_experiment.ps1",
    "-Mode", "finetune",
    "-Iterations", "$Iterations",
    "-TargetScore", "$TargetScore",
    "-Optimizer", $Optimizer,
    "-Width", "$Width",
    "-Height", "$Height",
    "-CapPort", "$CapPort",
    "-MaxRuntimeSec", "$MaxRuntimeSec"
)
if ($EngineRoot) { $args += @("-EngineRoot", $EngineRoot) }
if ($OutputRoot) { $args += @("-OutputRoot", $OutputRoot) }
if ($RunName) { $args += @("-RunName", $RunName) }
if ($SearchParamSpace) { $args += @("-SearchParamSpace", $SearchParamSpace) }
if ($InitialParamsOverride) { $args += @("-InitialParamsOverride", $InitialParamsOverride) }
if ($Headed) { $args += "-Headed" }

& powershell @args
exit $LASTEXITCODE
