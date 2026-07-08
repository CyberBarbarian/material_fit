param(
    [string]$StateDir = $env:MATERIAL_FIT_PERSISTENT_STATE_DIR
)

function Stop-ProcessTree {
    param([int]$ProcessId)
    if ($ProcessId -le 0) {
        return
    }
    $args = @("/F", "/T", "/PID", "$ProcessId")
    & taskkill @args | Out-Null
}

if (-not $StateDir) {
    Write-Error "StateDir is required. Pass -StateDir or set MATERIAL_FIT_PERSISTENT_STATE_DIR."
    exit 2
}

$statePath = Resolve-Path -LiteralPath $StateDir -ErrorAction SilentlyContinue
if (-not $statePath) {
    exit 0
}

$stateDirFull = $statePath.Path
$stopFile = Join-Path $stateDirFull "stop"
New-Item -ItemType File -Force -Path $stopFile | Out-Null

$pidFiles = @("worker.pid", "server.pid", "http.pid", "daemon.pid", "daemon_launcher.pid") |
    ForEach-Object { Join-Path $stateDirFull $_ }

Start-Sleep -Milliseconds 500
foreach ($pidFile in $pidFiles) {
    if (-not (Test-Path -LiteralPath $pidFile)) {
        continue
    }
    $pidText = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $pidText) {
        continue
    }
    $proc = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-ProcessTree -ProcessId $proc.Id
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

Remove-Item -LiteralPath (Join-Path $stateDirFull "ready.json") -Force -ErrorAction SilentlyContinue
exit 0
