param(
    [string]$StateDir = $env:MATERIAL_FIT_PERSISTENT_STATE_DIR
)

if (-not $StateDir) {
    Write-Error "StateDir is required. Pass -StateDir or set MATERIAL_FIT_PERSISTENT_STATE_DIR."
    exit 2
}

$statePath = Resolve-Path -LiteralPath $StateDir -ErrorAction SilentlyContinue
if (-not $statePath) {
    exit 0
}
$pidFile = Join-Path $statePath.Path "daemon.pid"
$readyFile = Join-Path $statePath.Path "ready.json"
if (Test-Path $pidFile) {
    $pidText = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pidText) {
        $proc = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $readyFile -Force -ErrorAction SilentlyContinue
exit 0
