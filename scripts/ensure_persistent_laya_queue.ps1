param(
    [string]$StateDir = $env:MATERIAL_FIT_PERSISTENT_STATE_DIR,
    [string]$HostName = "127.0.0.1",
    [int]$Port = $(if ($env:CAP_PORT) { [int]$env:CAP_PORT } else { 8787 }),
    [double]$TimeoutS = 120.0,
    [object]$CleanBeforeStart = $true,
    [object]$AllowExisting = $false
)

$ErrorActionPreference = "Stop"

function Convert-ToBool {
    param([object]$Value)
    if ($Value -is [bool]) {
        return $Value
    }
    if ($null -eq $Value) {
        return $false
    }
    $text = ([string]$Value).Trim()
    return -not ($text -eq "" -or $text -ieq "false" -or $text -eq "0" -or $text -ieq "no")
}

if (-not $StateDir) {
    throw "StateDir is required. Pass -StateDir or set MATERIAL_FIT_PERSISTENT_STATE_DIR."
}

$cleanBeforeStartEnabled = Convert-ToBool -Value $CleanBeforeStart
$allowExistingEnabled = Convert-ToBool -Value $AllowExisting
$stateDirFull = [System.IO.Path]::GetFullPath($StateDir)
$readyFile = Join-Path $stateDirFull "ready.json"
$pidFile = Join-Path $stateDirFull "daemon.pid"
$logDir = Join-Path $stateDirFull "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if ($allowExistingEnabled -and (Test-Path -LiteralPath $pidFile)) {
    $oldPid = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($oldPid) {
        $existing = Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue
        if ($existing -and (Test-Path -LiteralPath $readyFile)) {
            exit 0
        }
    }
}

$stopScript = Join-Path $PSScriptRoot "stop_persistent_laya_queue.ps1"
if ($cleanBeforeStartEnabled) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $stopScript -StateDir $stateDirFull
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to stop the previous persistent queue (exit $LASTEXITCODE)."
    }
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    $python = $venvPython
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python was not found. Run scripts\bootstrap.ps1 first."
    }
    $python = $pythonCommand.Source
}

$stdout = Join-Path $logDir "persistent_queue_stdout.log"
$stderr = Join-Path $logDir "persistent_queue_stderr.log"
$arguments = @(
    "-m", "material_fit.laya_capture.persistent_queue_daemon",
    "--state-dir=$stateDirFull",
    "--host=$HostName",
    "--port=$Port",
    "--timeout-s=$($TimeoutS.ToString([System.Globalization.CultureInfo]::InvariantCulture))"
)

$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ASCII

$deadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $deadline) {
    if (Test-Path -LiteralPath $readyFile) {
        exit 0
    }
    if ($process.HasExited) {
        break
    }
    Start-Sleep -Milliseconds 100
    $process.Refresh()
}

& powershell -NoProfile -ExecutionPolicy Bypass -File $stopScript -StateDir $stateDirFull | Out-Null
throw "Persistent queue daemon did not become ready; see $stdout and $stderr."
