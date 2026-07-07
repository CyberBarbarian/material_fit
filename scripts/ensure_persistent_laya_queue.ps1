param(
    [string]$StateDir = $env:MATERIAL_FIT_PERSISTENT_STATE_DIR,
    [string]$HostName = "127.0.0.1",
    [int]$Port = $(if ($env:CAP_PORT) { [int]$env:CAP_PORT } else { 8787 }),
    [double]$TimeoutS = 120.0
)

if (-not $StateDir) {
    Write-Error "StateDir is required. Pass -StateDir or set MATERIAL_FIT_PERSISTENT_STATE_DIR."
    exit 2
}

$statePath = Resolve-Path -LiteralPath $StateDir -ErrorAction SilentlyContinue
if (-not $statePath) {
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    $statePath = Resolve-Path -LiteralPath $StateDir
}
$stateDirFull = $statePath.Path
$readyFile = Join-Path $stateDirFull "ready.json"
$pidFile = Join-Path $stateDirFull "daemon.pid"
$logDir = Join-Path $stateDirFull "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (Test-Path $pidFile) {
    $oldPid = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($oldPid) {
        $proc = Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue
        if ($proc -and (Test-Path $readyFile)) {
            exit 0
        }
    }
}

$repoRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
$stdout = Join-Path $logDir "persistent_queue_stdout.log"
$stderr = Join-Path $logDir "persistent_queue_stderr.log"
$args = @(
    "-m", "material_fit.laya_capture.persistent_queue_daemon",
    "--state-dir", $stateDirFull,
    "--host", $HostName,
    "--port", "$Port",
    "--timeout-s", "$TimeoutS"
)
$proc = Start-Process -FilePath "python" -ArgumentList $args -WorkingDirectory $repoRoot.Path -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
Set-Content -LiteralPath $pidFile -Value $proc.Id -Encoding ASCII

$deadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $deadline) {
    if (Test-Path $readyFile) {
        exit 0
    }
    Start-Sleep -Milliseconds 100
}

Write-Error "persistent queue daemon did not become ready; see $stdout and $stderr"
exit 1
